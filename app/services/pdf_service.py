from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader

from app.services.document_models import (
    DocumentBlock,
    PDFExtractionResult,
    PDFPageAnalysis,
    PDFPageSpec,
)

class PDFProcessingError(Exception):
    pass


def extract_pdf_text(
    file_path: Path,
    *,
    enable_ocr: bool = True,
    tesseract_cmd: str | None = None,
    ocr_languages: str = "tur+eng",
) -> PDFExtractionResult:
    try:
        import fitz

        return _extract_with_pymupdf(
            file_path=file_path,
            enable_ocr=enable_ocr,
            tesseract_cmd=tesseract_cmd,
            ocr_languages=ocr_languages,
            fitz_module=fitz,
        )
    except ImportError:
        return _extract_with_pypdf(file_path)
    except Exception as exc:
        raise PDFProcessingError("PDF dosyasi okunamadi.") from exc


def _extract_with_pymupdf(
    *,
    file_path: Path,
    enable_ocr: bool,
    tesseract_cmd: str | None,
    ocr_languages: str,
    fitz_module: Any,
) -> PDFExtractionResult:
    try:
        document = fitz_module.open(str(file_path))
    except Exception as exc:
        raise PDFProcessingError("PDF dosyasi okunamadi.") from exc

    pages: list[str] = []
    page_specs: list[PDFPageSpec] = []
    analyzed_pages: list[PDFPageAnalysis] = []

    if tesseract_cmd:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    for page in document:
        analyzed_page = _extract_page_analysis(
            page,
            enable_ocr=enable_ocr,
            ocr_languages=ocr_languages,
            fitz_module=fitz_module,
        )
        pages.append(analyzed_page.page_text)
        analyzed_pages.append(analyzed_page)
        page_specs.append(
            PDFPageSpec(
                width=float(page.rect.width or 595),
                height=float(page.rect.height or 842),
                rotation=int(page.rotation or 0),
            )
        )

    joined_text = "\n".join(filter(None, pages))
    if not joined_text:
        raise PDFProcessingError(
            "PDF icinden metin cikarilamadi. Dosya taranmis goruntu olabilir."
        )

    return PDFExtractionResult(
        pages=pages,
        page_specs=page_specs,
        analyzed_pages=analyzed_pages,
        page_count=len(pages),
        word_count=len(joined_text.split()),
        char_count=len(joined_text),
    )


def _extract_with_pypdf(file_path: Path) -> PDFExtractionResult:
    try:
        reader = PdfReader(str(file_path))
    except Exception as exc:
        raise PDFProcessingError("PDF dosyasi okunamadi.") from exc

    pages: list[str] = []
    page_specs: list[PDFPageSpec] = []
    analyzed_pages: list[PDFPageAnalysis] = []

    for page in reader.pages:
        raw_text = page.extract_text() or ""
        normalized_text = _normalize_page_text(raw_text)
        pages.append(normalized_text)
        page_specs.append(
            PDFPageSpec(
                width=float(page.mediabox.width or 595),
                height=float(page.mediabox.height or 842),
                rotation=int(page.get("/Rotate", 0) or 0),
            )
        )
        analyzed_pages.append(
            PDFPageAnalysis(
                blocks=_build_blocks_from_plain_text(normalized_text),
                page_text=normalized_text,
            )
        )

    joined_text = "\n".join(filter(None, pages))
    if not joined_text:
        raise PDFProcessingError(
            "PDF icinden metin cikarilamadi. Dosya taranmis goruntu olabilir."
        )

    return PDFExtractionResult(
        pages=pages,
        page_specs=page_specs,
        analyzed_pages=analyzed_pages,
        page_count=len(pages),
        word_count=len(joined_text.split()),
        char_count=len(joined_text),
    )


def _extract_page_analysis(
    page: Any,
    *,
    enable_ocr: bool,
    ocr_languages: str,
    fitz_module: Any,
) -> PDFPageAnalysis:
    page_dict = page.get_text("dict")
    blocks = _extract_structured_blocks(page_dict, float(page.rect.height))

    if not blocks and enable_ocr:
        ocr_text = _ocr_page(page, ocr_languages, fitz_module)
        blocks = _build_blocks_from_plain_text(ocr_text)

    page_text = _rebuild_page_text(blocks)
    return PDFPageAnalysis(blocks=blocks, page_text=page_text)


def _extract_structured_blocks(page_dict: dict, page_height: float) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []

    for raw_block in page_dict.get("blocks", []):
        if raw_block.get("type") != 0:
            continue

        block_lines: list[str] = []
        span_sizes: list[float] = []

        for line in raw_block.get("lines", []):
            span_texts: list[str] = []
            for span in line.get("spans", []):
                text = (span.get("text") or "").strip()
                if text:
                    span_texts.append(text)
                    span_sizes.append(float(span.get("size") or 11))
            if span_texts:
                block_lines.append(" ".join(span_texts))

        raw_text = "\n".join(block_lines).strip()
        if not raw_text:
            continue

        cleaned_text = _normalize_page_text(raw_text)
        if not cleaned_text:
            continue

        font_size = max(span_sizes) if span_sizes else 11.0
        bbox = tuple(raw_block.get("bbox", (0, 0, 0, 0)))
        kind, marker, columns = _classify_block(cleaned_text, font_size, bbox, page_height)
        blocks.append(
            DocumentBlock(
                kind=kind,
                text=cleaned_text,
                font_size=font_size,
                bbox=bbox,
                marker=marker,
                columns=columns,
            )
        )

    return blocks


def _classify_block(
    text: str,
    font_size: float,
    bbox: tuple[float, float, float, float],
    page_height: float,
) -> tuple[str, str, list[list[str]]]:
    stripped = text.strip()
    marker = ""
    columns: list[list[str]] = []

    if _looks_like_table(stripped):
        columns = _parse_table(stripped)
        return "table", marker, columns

    bullet_match = re.match(r"^([\-*•]|[0-9]+[.)])\s+(.*)$", stripped)
    if bullet_match:
        marker = bullet_match.group(1)
        return "bullet", marker, columns

    if bbox[1] > page_height * 0.82 and (font_size <= 10.5 or len(stripped) < 180):
        return "footnote", marker, columns

    if font_size >= 13.5 or _looks_like_heading(stripped):
        return "heading", marker, columns

    return "paragraph", marker, columns


def _looks_like_heading(text: str) -> bool:
    if len(text) > 140:
        return False
    if text.isupper():
        return True
    significant_words = [word for word in text.split() if len(word) > 2]
    if 0 < len(significant_words) <= 12 and text == text.title():
        return True
    return False


def _looks_like_table(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    tabbed_lines = sum(1 for line in lines if "\t" in line or re.search(r"\s{3,}", line))
    piped_lines = sum(1 for line in lines if "|" in line)
    return tabbed_lines >= 2 or piped_lines >= 2


def _parse_table(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if "|" in stripped:
            parts = [part.strip() for part in stripped.split("|") if part.strip()]
        else:
            parts = [part.strip() for part in re.split(r"\s{3,}", stripped) if part.strip()]

        if parts:
            rows.append(parts)
    return rows


def _ocr_page(page: Any, ocr_languages: str, fitz_module: Any) -> str:
    try:
        import pytesseract
        from PIL import Image

        pixmap = page.get_pixmap(matrix=fitz_module.Matrix(2, 2), alpha=False)
        image = Image.open(BytesIO(pixmap.tobytes("png")))
        return pytesseract.image_to_string(image, lang=ocr_languages).strip()
    except Exception:
        return ""


def _build_blocks_from_plain_text(text: str) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    for paragraph in text.split("\n\n"):
        cleaned = _normalize_page_text(paragraph)
        if not cleaned:
            continue
        kind, marker, columns = _classify_block(cleaned, 11.0, (0, 0, 0, 0), 842)
        blocks.append(
            DocumentBlock(
                kind=kind,
                text=cleaned,
                font_size=11.0,
                marker=marker,
                columns=columns,
            )
        )
    return blocks


def _rebuild_page_text(blocks: list[DocumentBlock]) -> str:
    return "\n\n".join(block.text for block in blocks if block.text.strip()).strip()


def _normalize_page_text(raw_text: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines()]
    filtered_lines = [line for line in lines if line]
    if not filtered_lines:
        return ""

    paragraphs: list[str] = []
    current_paragraph = ""

    for line in filtered_lines:
        if line.endswith("-") and len(line) > 1:
            current_paragraph += line[:-1]
            continue

        if not current_paragraph:
            current_paragraph = line
            continue

        if _should_join_lines(current_paragraph, line):
            current_paragraph = f"{current_paragraph} {line}"
        else:
            paragraphs.append(current_paragraph)
            current_paragraph = line

    if current_paragraph:
        paragraphs.append(current_paragraph)

    return "\n\n".join(paragraphs).strip()


def _should_join_lines(current: str, next_line: str) -> bool:
    if current.endswith((".", ":", ";", "!", "?")):
        return False
    if next_line[:1].islower():
        return True
    if len(current) < 70:
        return True
    return False
