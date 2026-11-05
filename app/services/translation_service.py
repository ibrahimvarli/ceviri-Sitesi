from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from threading import Lock
from time import sleep
from urllib import parse, request
from urllib.error import HTTPError, URLError

from app.services.document_models import DocumentBlock, PDFPageAnalysis


class TranslationServiceError(Exception):
    pass


LANGUAGE_OPTIONS = {
    "tr": "Turkce",
    "en": "English",
    "de": "Deutsch",
    "fr": "Francais",
    "es": "Espanol",
    "it": "Italiano",
    "pt": "Portugues",
    "ru": "Russkiy",
    "ar": "Arabic",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese (Simplified)",
}

SOURCE_LANGUAGE_OPTIONS = {"auto": "Otomatik Algila", **LANGUAGE_OPTIONS}
_translator_lock = Lock()
_translator_cache: dict[tuple[str, str], object] = {}
_argostranslate_package = None
_argostranslate_translate = None
_transformer_lock = Lock()
_transformer_cache: dict[tuple[str, str], object] = {}
_ENABLE_TRANSFORMERS_FALLBACK = os.getenv("ENABLE_TRANSFORMERS_FALLBACK", "false").lower() == "true"
_LIBRETRANSLATE_CONNECT_TIMEOUT = float(os.getenv("LIBRETRANSLATE_CONNECT_TIMEOUT", "4"))
_LIBRETRANSLATE_READ_TIMEOUT = float(os.getenv("LIBRETRANSLATE_READ_TIMEOUT", "12"))
_FREE_TRANSLATE_TIMEOUT = float(os.getenv("FREE_TRANSLATE_TIMEOUT", "10"))


@dataclass
class TranslationResult:
    translated_pages: list[str]
    translated_page_analyses: list[PDFPageAnalysis]
    source_language: str
    target_language: str
    engine_name: str


@dataclass(frozen=True)
class SelectedTranslator:
    translator: object
    engine_name: str


def list_source_languages() -> dict[str, str]:
    return SOURCE_LANGUAGE_OPTIONS


def list_target_languages() -> dict[str, str]:
    return LANGUAGE_OPTIONS


def _chunk_text(text: str, limit: int = 4200) -> list[str]:
    stripped = _prepare_text_for_translation(text)
    if not stripped:
        return [""]

    chunks: list[str] = []
    current = ""

    for paragraph in stripped.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        candidate = paragraph if not current else f"{current}\n{paragraph}"
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(paragraph) <= limit:
            current = paragraph
            continue

        sentence_buffer = ""
        for word in paragraph.split():
            tentative = word if not sentence_buffer else f"{sentence_buffer} {word}"
            if len(tentative) <= limit:
                sentence_buffer = tentative
            else:
                chunks.append(sentence_buffer)
                sentence_buffer = word
        current = sentence_buffer

    if current:
        chunks.append(current)

    return chunks or [""]


def translate_pages(
    analyzed_pages: list[PDFPageAnalysis],
    source_language: str,
    target_language: str,
    max_workers: int = 6,
    progress_callback: Callable[[int, int], None] | None = None,
    glossary_path: Path | None = None,
) -> TranslationResult:
    translated_pages = [""] * len(analyzed_pages)
    translated_page_analyses: list[PDFPageAnalysis | None] = [None] * len(analyzed_pages)
    page_entries = list(enumerate(analyzed_pages))
    completed_pages = 0
    total_pages = len(page_entries)
    resolved_source_language = _resolve_source_language(analyzed_pages, source_language)
    glossary = _load_glossary(glossary_path, resolved_source_language, target_language)
    selected_translator = _get_open_source_translator(
        resolved_source_language,
        target_language,
    )
    engine_name = _get_runtime_engine_name(selected_translator)

    if total_pages == 0:
        return TranslationResult(
            translated_pages=[],
            translated_page_analyses=[],
            source_language=resolved_source_language,
            target_language=target_language,
            engine_name=engine_name,
        )

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, total_pages))) as executor:
        futures = {
            executor.submit(
                _translate_page,
                page_index,
                page_analysis,
                resolved_source_language,
                target_language,
                glossary,
                selected_translator.translator,
            ): page_index
            for page_index, page_analysis in page_entries
        }

        for future in as_completed(futures):
            page_index = futures[future]
            try:
                translated_page_text, translated_page_analysis = future.result()
                translated_pages[page_index] = translated_page_text
                translated_page_analyses[page_index] = translated_page_analysis
            except Exception as exc:
                detailed_message = str(exc).strip()
                raise TranslationServiceError(
                    detailed_message
                    or "Ceviri servisine baglanilamadi veya ceviri tamamlanamadi."
                ) from exc

            completed_pages += 1
            if progress_callback is not None:
                progress_callback(completed_pages, total_pages)

    return TranslationResult(
        translated_pages=translated_pages,
        translated_page_analyses=[
            page_analysis
            for page_analysis in translated_page_analyses
            if page_analysis is not None
        ],
        source_language=resolved_source_language,
        target_language=target_language,
        engine_name=_get_runtime_engine_name(selected_translator),
    )


def _translate_page(
    page_index: int,
    page_analysis: PDFPageAnalysis,
    source_language: str,
    target_language: str,
    glossary: dict[str, str],
    translator: object,
) -> tuple[str, PDFPageAnalysis]:
    if not page_analysis.page_text.strip():
        return "", PDFPageAnalysis(blocks=[], page_text="")

    translated_blocks: list[DocumentBlock] = []

    for block in page_analysis.blocks:
        translated_blocks.append(
            _translate_block(block, source_language, target_language, glossary, translator)
        )

    translated_text = "\n\n".join(
        block.text for block in translated_blocks if block.text.strip()
    ).strip()
    return (
        translated_text,
        PDFPageAnalysis(blocks=translated_blocks, page_text=translated_text),
    )


def _translate_block(
    block: DocumentBlock,
    source_language: str,
    target_language: str,
    glossary: dict[str, str],
    translator: object,
) -> DocumentBlock:
    if not block.text.strip():
        return block.with_text("")

    if block.kind == "table" and block.columns:
        translated_rows: list[list[str]] = []
        for row in block.columns:
            translated_row = [
                _translate_text(cell, glossary, translator)
                for cell in row
            ]
            translated_rows.append(translated_row)
        translated_text = "\n".join(" | ".join(row) for row in translated_rows)
        return DocumentBlock(
            kind=block.kind,
            text=translated_text,
            font_size=block.font_size,
            bbox=block.bbox,
            marker=block.marker,
            columns=translated_rows,
        )

    text_to_translate = block.text
    if block.kind == "bullet" and block.marker:
        bullet_body = re.sub(r"^([\-*•]|[0-9]+[.)])\s+", "", block.text)
        translated_body = _translate_text(
            bullet_body,
            glossary,
            translator,
        )
        translated_text = f"{block.marker} {translated_body}".strip()
    else:
        translated_text = _translate_text(
            text_to_translate,
            glossary,
            translator,
        )

    return block.with_text(translated_text)


def _prepare_text_for_translation(text: str) -> str:
    normalized_lines = [line.strip() for line in text.splitlines()]
    compact_lines: list[str] = []

    for line in normalized_lines:
        if not line:
            compact_lines.append("")
            continue

        if compact_lines and compact_lines[-1] and compact_lines[-1].endswith("-"):
            compact_lines[-1] = f"{compact_lines[-1][:-1]}{line}"
        else:
            compact_lines.append(line)

    paragraphs: list[str] = []
    current = ""
    for line in compact_lines:
        if not line:
            if current:
                paragraphs.append(current)
                current = ""
            continue

        if not current:
            current = line
        else:
            current = f"{current} {line}"

    if current:
        paragraphs.append(current)

    return "\n\n".join(paragraphs).strip()


def _postprocess_translation(text: str) -> str:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n")]
    cleaned_paragraphs: list[str] = []

    for paragraph in paragraphs:
        if not paragraph:
            continue

        cleaned = " ".join(paragraph.split())
        cleaned = cleaned.replace(" ,", ",").replace(" .", ".")
        cleaned = cleaned.replace(" !", "!").replace(" ?", "?")
        cleaned = cleaned.replace(" :", ":").replace(" ;", ";")
        cleaned = cleaned.replace("( ", "(").replace(" )", ")")
        cleaned = cleaned.replace("[ ", "[").replace(" ]", "]")
        cleaned = cleaned.replace("{ ", "{").replace(" }", "}")
        cleaned = cleaned.replace(" ’", "’").replace(" ' ", "'")
        cleaned_paragraphs.append(cleaned.strip())

    return "\n\n".join(cleaned_paragraphs).strip()


def _translate_text(
    text: str,
    glossary: dict[str, str],
    translator: object,
) -> str:
    translated_chunks: list[str] = []
    for chunk in _chunk_text(text):
        if not chunk:
            continue
        protected_text, placeholders = _apply_glossary_placeholders(chunk, glossary)
        translated_chunk = translator.translate(protected_text)
        translated_chunks.append(_restore_glossary_placeholders(translated_chunk, placeholders))
    return _postprocess_translation("\n\n".join(translated_chunks))


def _get_open_source_translator(
    source_language: str, target_language: str
) -> SelectedTranslator:
    candidates = _build_translator_candidates(source_language, target_language)
    if not candidates:
        raise TranslationServiceError(
            "Kullanilabilir bir ceviri motoru hazirlanamadi. Bagimliliklari ve ceviri ayarlarini kontrol edin."
        )

    failover_translator = _FailoverTranslator(candidates)
    return SelectedTranslator(
        translator=failover_translator,
        engine_name=failover_translator.engine_name,
    )


def _build_translator_candidates(
    source_language: str,
    target_language: str,
) -> list[SelectedTranslator]:
    candidates: list[SelectedTranslator] = []
    build_errors: list[Exception] = []

    argos_error: Exception | None = None

    try:
        candidates.append(
            SelectedTranslator(
                translator=_get_argos_translator(source_language, target_language),
                engine_name="Argos Translate",
            )
        )
    except Exception as exc:
        argos_error = exc
        build_errors.append(exc)

    transformers_error: Exception | None = None
    if _ENABLE_TRANSFORMERS_FALLBACK:
        try:
            candidates.append(
                SelectedTranslator(
                    translator=_get_transformers_translator(source_language, target_language),
                    engine_name="Helsinki-NLP Transformers",
                )
            )
        except Exception as exc:
            transformers_error = exc
            build_errors.append(exc)

    try:
        candidates.append(
            SelectedTranslator(
                translator=_get_libretranslate_translator(source_language, target_language),
                engine_name="LibreTranslate",
            )
        )
    except Exception as exc:
        build_errors.append(exc)

    try:
        candidates.append(
            SelectedTranslator(
                translator=_get_google_free_translator(source_language, target_language),
                engine_name="Google Translate Free",
            )
        )
    except Exception as exc:
        build_errors.append(exc)

    if candidates:
        return candidates

    cause = argos_error or transformers_error or (build_errors[0] if build_errors else None)
    raise TranslationServiceError(
        "Acik kaynak ceviri motoru hazirlanamadi. Argos Translate, Transformers, LibreTranslate veya ucretsiz HTTP fallback ayarlarini kontrol edin."
    ) from cause


def _get_runtime_engine_name(selected_translator: SelectedTranslator) -> str:
    return str(
        getattr(selected_translator.translator, "engine_name", selected_translator.engine_name)
    )


class _FailoverTranslator:
    def __init__(self, translators: list[SelectedTranslator]) -> None:
        self.translators = translators
        self._active_index = 0
        self._lock = Lock()
        self.engine_name = translators[0].engine_name

    def translate(self, text: str) -> str:
        errors: list[str] = []

        with self._lock:
            start_index = self._active_index
            ordered_translators = (
                self.translators[start_index:] + self.translators[:start_index]
            )

            for offset, selected_translator in enumerate(ordered_translators):
                try:
                    translated_text = selected_translator.translator.translate(text)
                    resolved_index = (start_index + offset) % len(self.translators)
                    self._active_index = resolved_index
                    self.engine_name = selected_translator.engine_name
                    return translated_text
                except Exception as exc:
                    errors.append(f"{selected_translator.engine_name}: {exc}")

        joined_errors = " | ".join(errors)
        raise TranslationServiceError(
            "Tum ceviri motorlari basarisiz oldu. " + joined_errors
        )


def _get_argos_translator(source_language: str, target_language: str):
    source_language = _normalize_language_code(source_language)
    target_language = _normalize_language_code(target_language)
    cache_key = (source_language, target_language)

    with _translator_lock:
        translator = _translator_cache.get(cache_key)
        if translator is not None:
            return translator

        translator = _build_argos_translator(source_language, target_language)
        _translator_cache[cache_key] = translator
        return translator


def _build_argos_translator(source_language: str, target_language: str):
    _, argos_translate = _load_argos_modules()
    installed_languages = argos_translate.get_installed_languages()
    from_language = next(
        (language for language in installed_languages if language.code == source_language),
        None,
    )
    to_language = next(
        (language for language in installed_languages if language.code == target_language),
        None,
    )

    if from_language is None or to_language is None:
        _install_argos_package(source_language, target_language)
        installed_languages = argos_translate.get_installed_languages()
        from_language = next(
            (language for language in installed_languages if language.code == source_language),
            None,
        )
        to_language = next(
            (language for language in installed_languages if language.code == target_language),
            None,
        )

    if from_language is None or to_language is None:
        raise TranslationServiceError("Acik kaynak dil paketi bulunamadi veya yuklenemedi.")

    return from_language.get_translation(to_language)


def _install_argos_package(source_language: str, target_language: str) -> None:
    argos_package, _ = _load_argos_modules()
    argos_package.update_package_index()
    available_packages = argos_package.get_available_packages()
    package = next(
        (
            item
            for item in available_packages
            if item.from_code == source_language and item.to_code == target_language
        ),
        None,
    )

    if package is None:
        raise TranslationServiceError(
            f"Argos Translate icin {source_language} -> {target_language} dil paketi bulunamadi."
        )

    download_path = package.download()
    argos_package.install_from_path(download_path)


def _load_argos_modules():
    global _argostranslate_package, _argostranslate_translate
    if _argostranslate_package is not None and _argostranslate_translate is not None:
        return _argostranslate_package, _argostranslate_translate

    try:
        import argostranslate.package as argos_package
        import argostranslate.translate as argos_translate
    except ImportError as exc:
        raise TranslationServiceError(
            "Argos Translate bagimliliklari eksik. Lutfen requirements.txt bagimliliklarini kurun."
        ) from exc

    _argostranslate_package = argos_package
    _argostranslate_translate = argos_translate
    return _argostranslate_package, _argostranslate_translate


def _get_transformers_translator(source_language: str, target_language: str):
    source_language = _normalize_language_code(source_language)
    target_language = _normalize_language_code(target_language)
    cache_key = (source_language, target_language)

    with _transformer_lock:
        translator = _transformer_cache.get(cache_key)
        if translator is not None:
            return translator

        translator = _build_transformers_translator(source_language, target_language)
        _transformer_cache[cache_key] = translator
        return translator


def _build_transformers_translator(source_language: str, target_language: str):
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise TranslationServiceError(
            "Transformers ceviri modeli kullanilamadi. Gerekli bagimliliklar eksik."
        ) from exc

    model_name = f"Helsinki-NLP/opus-mt-{source_language}-{target_language}"
    return _TransformersTranslator(pipeline("translation", model=model_name, tokenizer=model_name))


class _TransformersTranslator:
    def __init__(self, translator_pipeline) -> None:
        self.translator_pipeline = translator_pipeline

    def translate(self, text: str) -> str:
        result = self.translator_pipeline(text, clean_up_tokenization_spaces=True)
        if not result:
            return ""
        return str(result[0].get("translation_text", "")).strip()


def _get_libretranslate_translator(source_language: str, target_language: str):
    return _LibreTranslateTranslator(
        base_urls=_get_libretranslate_urls(),
        api_key=os.getenv("LIBRETRANSLATE_API_KEY", ""),
        source_language=source_language,
        target_language=target_language,
    )


def _get_libretranslate_urls() -> list[str]:
    configured = os.getenv("LIBRETRANSLATE_URL", "").strip()
    urls = []
    if configured:
        urls.append(configured)

    urls.extend(
        [
            "https://libretranslate.com/translate",
            "https://translate.argosopentech.com/translate",
        ]
    )

    unique_urls: list[str] = []
    for url in urls:
        normalized = url.strip()
        if normalized and normalized not in unique_urls:
            unique_urls.append(normalized)
    return unique_urls


class _LibreTranslateTranslator:
    def __init__(
        self,
        *,
        base_urls: list[str],
        api_key: str,
        source_language: str,
        target_language: str,
    ) -> None:
        self.base_urls = base_urls
        self.api_key = api_key
        self.source_language = source_language
        self.target_language = target_language

    def translate(self, text: str) -> str:
        payload = {
            "q": text,
            "source": self.source_language,
            "target": self.target_language,
            "format": "text",
        }
        if self.api_key:
            payload["api_key"] = self.api_key

        last_error: Exception | None = None
        for base_url in self.base_urls:
            try:
                result = _post_json(
                    base_url,
                    payload,
                    timeout=max(
                        _LIBRETRANSLATE_CONNECT_TIMEOUT,
                        _LIBRETRANSLATE_READ_TIMEOUT,
                    ),
                )
                return str(result.get("translatedText", "")).strip()
            except Exception as exc:
                last_error = exc
                sleep(0.35)

        raise TranslationServiceError(
            "LibreTranslate tabanli ceviri servisine ulasilamadi."
        ) from last_error


def _get_google_free_translator(source_language: str, target_language: str):
    return _GoogleFreeTranslator(
        source_language=source_language,
        target_language=target_language,
    )


class _GoogleFreeTranslator:
    def __init__(self, *, source_language: str, target_language: str) -> None:
        self.source_language = source_language
        self.target_language = target_language

    def translate(self, text: str) -> str:
        query = parse.urlencode(
            {
                "client": "gtx",
                "sl": self.source_language,
                "tl": self.target_language,
                "dt": "t",
                "q": text,
            }
        )
        url = f"https://translate.googleapis.com/translate_a/single?{query}"
        response = request.urlopen(url, timeout=_FREE_TRANSLATE_TIMEOUT)
        raw_payload = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw_payload)
        segments = parsed[0] if parsed and isinstance(parsed[0], list) else []
        translated_text = "".join(
            str(segment[0]) for segment in segments if isinstance(segment, list) and segment
        ).strip()
        if not translated_text:
            raise TranslationServiceError("Ucretsiz HTTP ceviri servisinden bos yanit alindi.")
        return translated_text


def _post_json(url: str, payload: dict[str, object], timeout: float) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            raw_payload = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise TranslationServiceError(
            f"HTTP {exc.code}: {error_body[:240].strip() or 'ceviri servisi hatasi'}"
        ) from exc
    except URLError as exc:
        raise TranslationServiceError("Ceviri servisine baglanti kurulamadi.") from exc

    try:
        return json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise TranslationServiceError("Ceviri servisinden gecersiz JSON yaniti alindi.") from exc


def _resolve_source_language(
    analyzed_pages: list[PDFPageAnalysis], source_language: str
) -> str:
    if source_language != "auto":
        return _normalize_language_code(source_language)

    sample_text = "\n".join(
        page.page_text for page in analyzed_pages[:3] if page.page_text.strip()
    ).strip()
    if not sample_text:
        return "en"

    try:
        from langdetect import DetectorFactory, detect
        from langdetect.lang_detect_exception import LangDetectException
    except ImportError:
        return "en"

    try:
        DetectorFactory.seed = 0
        detected = detect(sample_text)
    except LangDetectException:
        return "en"
    except ImportError:
        return "en"

    return _normalize_language_code(detected)


def _normalize_language_code(language_code: str) -> str:
    normalized = language_code.lower()
    if normalized.startswith("zh"):
        return "zh"
    if normalized == "pt-br":
        return "pt"
    return normalized


def _load_glossary(
    glossary_path: Path | None,
    source_language: str,
    target_language: str,
) -> dict[str, str]:
    if glossary_path is None or not glossary_path.exists():
        return {}

    try:
        payload = json.loads(glossary_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    pair_key = f"{source_language}:{target_language}"
    pair_glossary = payload.get(pair_key, {})
    return {
        str(source).strip(): str(target).strip()
        for source, target in pair_glossary.items()
        if str(source).strip() and str(target).strip()
    }


def _apply_glossary_placeholders(
    text: str, glossary: dict[str, str]
) -> tuple[str, dict[str, str]]:
    protected_text = text
    placeholders: dict[str, str] = {}

    for index, (source_term, target_term) in enumerate(
        sorted(glossary.items(), key=lambda item: len(item[0]), reverse=True)
    ):
        placeholder = f"GLS{index}TOKEN"
        pattern = re.compile(re.escape(source_term), re.IGNORECASE)
        protected_text, replacements = pattern.subn(placeholder, protected_text)
        if replacements:
            placeholders[placeholder] = target_term

    return protected_text, placeholders


def _restore_glossary_placeholders(text: str, placeholders: dict[str, str]) -> str:
    restored = text
    for placeholder, target_term in placeholders.items():
        restored = restored.replace(placeholder, target_term)
    return restored
