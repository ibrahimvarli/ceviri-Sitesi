from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
from threading import Lock, Thread
from uuid import uuid4

from app.services.export_service import export_translated_pages
from app.services.pdf_service import PDFProcessingError, extract_pdf_text
from app.services.translation_service import TranslationServiceError, translate_pages


@dataclass
class TranslationJob:
    job_id: str
    status: str
    message: str
    original_filename: str
    source_language: str
    target_language: str
    progress: int = 0
    processed_pages: int = 0
    page_count: int = 0
    word_count: int = 0
    char_count: int = 0
    translation_engine: str | None = None
    download_url: str | None = None
    preview_pages: list[dict[str, str | int]] = field(default_factory=list)
    preview_page_count: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    completed_at: str | None = None
    error: str | None = None


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, TranslationJob] = {}
        self._lock = Lock()

    def create_job(
        self, original_filename: str, source_language: str, target_language: str
    ) -> TranslationJob:
        job = TranslationJob(
            job_id=uuid4().hex,
            status="queued",
            message="Ceviri siraya alindi.",
            original_filename=original_filename,
            source_language=source_language,
            target_language=target_language,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def update_job(self, job_id: str, **changes: object) -> TranslationJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in changes.items():
                setattr(job, key, value)
            return job

    def get_job(self, job_id: str) -> TranslationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def serialize_job(self, job_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return asdict(job)


job_store = JobStore()
logger = logging.getLogger(__name__)


def start_translation_job(
    *,
    job_id: str,
    upload_path: Path,
    export_folder: Path,
    original_filename: str,
    source_language: str,
    target_language: str,
    max_workers: int,
    preview_limit: int,
    enable_ocr: bool,
    tesseract_cmd: str | None,
    ocr_languages: str,
    glossary_path: Path | None,
) -> None:
    worker = Thread(
        target=_run_translation_job,
        kwargs={
            "job_id": job_id,
            "upload_path": upload_path,
            "export_folder": export_folder,
            "original_filename": original_filename,
            "source_language": source_language,
            "target_language": target_language,
            "max_workers": max_workers,
            "preview_limit": preview_limit,
            "enable_ocr": enable_ocr,
            "tesseract_cmd": tesseract_cmd,
            "ocr_languages": ocr_languages,
            "glossary_path": glossary_path,
        },
        daemon=True,
    )
    worker.start()


def _run_translation_job(
    *,
    job_id: str,
    upload_path: Path,
    export_folder: Path,
    original_filename: str,
    source_language: str,
    target_language: str,
    max_workers: int,
    preview_limit: int,
    enable_ocr: bool,
    tesseract_cmd: str | None,
    ocr_languages: str,
    glossary_path: Path | None,
) -> None:
    try:
        job_store.update_job(
            job_id,
            status="processing",
            message="PDF analizi basladi.",
            progress=3,
        )
        extraction_result = extract_pdf_text(
            upload_path,
            enable_ocr=enable_ocr,
            tesseract_cmd=tesseract_cmd or None,
            ocr_languages=ocr_languages,
        )

        job_store.update_job(
            job_id,
            message="Metin cikarildi, sayfalar paralel olarak cevriliyor.",
            progress=10,
            page_count=extraction_result.page_count,
            word_count=extraction_result.word_count,
            char_count=extraction_result.char_count,
        )

        def on_progress(processed_pages: int, total_pages: int) -> None:
            completion_ratio = processed_pages / total_pages if total_pages else 1
            progress = min(92, 10 + int(completion_ratio * 80))
            job_store.update_job(
                job_id,
                processed_pages=processed_pages,
                page_count=total_pages,
                progress=progress,
                message=f"Ceviri devam ediyor: {processed_pages}/{total_pages} sayfa tamamlandi.",
            )

        translation_result = translate_pages(
            extraction_result.analyzed_pages,
            source_language,
            target_language,
            max_workers=max_workers,
            progress_callback=on_progress,
            glossary_path=glossary_path,
        )

        job_store.update_job(
            job_id,
            message="Ceviri tamamlandi, sonuc dosyasi hazirlaniyor.",
            progress=95,
            processed_pages=extraction_result.page_count,
        )

        export_filename = export_translated_pages(
            original_filename=original_filename,
            source_language=translation_result.source_language,
            target_language=translation_result.target_language,
            original_page_analyses=extraction_result.analyzed_pages,
            translated_page_analyses=translation_result.translated_page_analyses,
            page_specs=extraction_result.page_specs,
            export_folder=export_folder,
        )

        preview_pages = [
            {
                "page": index,
                "source": source or "Bu sayfada metin bulunamadi.",
                "translated": translated or "Bu sayfada cevrilecek metin bulunamadi.",
            }
            for index, (source, translated) in enumerate(
                zip(
                    extraction_result.pages[:preview_limit],
                    translation_result.translated_pages[:preview_limit],
                ),
                start=1,
            )
        ]

        job_store.update_job(
            job_id,
            status="completed",
            message="PDF basariyla cevrildi.",
            progress=100,
            processed_pages=extraction_result.page_count,
            translation_engine=translation_result.engine_name,
            download_url=f"/downloads/{export_filename}",
            preview_pages=preview_pages,
            preview_page_count=len(preview_pages),
            completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    except (PDFProcessingError, TranslationServiceError) as exc:
        job_store.update_job(
            job_id,
            status="failed",
            progress=100,
            error=str(exc),
            message=str(exc),
            completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    except Exception as exc:
        logger.exception("Ceviri isleminde beklenmeyen hata olustu: %s", exc)
        detailed_error = f"{type(exc).__name__}: {exc}".strip(": ")
        job_store.update_job(
            job_id,
            status="failed",
            progress=100,
            error=detailed_error or "Islem sirasinda beklenmeyen bir hata olustu.",
            message=detailed_error or "Islem sirasinda beklenmeyen bir hata olustu.",
            completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    finally:
        upload_path.unlink(missing_ok=True)
