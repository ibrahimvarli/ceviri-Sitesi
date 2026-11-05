from __future__ import annotations

from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from app.services.job_service import job_store, start_translation_job
from app.services.translation_service import list_source_languages, list_target_languages
from app.utils.file_utils import build_unique_upload_path, is_allowed_file


web_bp = Blueprint("web", __name__)


@web_bp.get("/")
def index():
    return render_template(
        "index.html",
        source_languages=list_source_languages(),
        target_languages=list_target_languages(),
        app_name=current_app.config["APP_NAME"],
    )


@web_bp.post("/translate")
def translate_document():
    uploaded_file = request.files.get("pdf_file")
    source_language = request.form.get(
        "source_language", current_app.config["DEFAULT_SOURCE_LANGUAGE"]
    )
    target_language = request.form.get(
        "target_language", current_app.config["DEFAULT_TARGET_LANGUAGE"]
    )

    if uploaded_file is None or not uploaded_file.filename:
        return jsonify({"ok": False, "message": "Lutfen bir PDF dosyasi secin."}), 400

    if not is_allowed_file(
        uploaded_file.filename, current_app.config["ALLOWED_EXTENSIONS"]
    ):
        return (
            jsonify({"ok": False, "message": "Sadece PDF uzantili dosyalar kabul edilir."}),
            400,
        )

    upload_path = build_unique_upload_path(
        uploaded_file.filename, current_app.config["UPLOAD_FOLDER"]
    )
    uploaded_file.save(upload_path)

    job = job_store.create_job(
        original_filename=uploaded_file.filename,
        source_language=source_language,
        target_language=target_language,
    )

    start_translation_job(
        job_id=job.job_id,
        upload_path=upload_path,
        export_folder=current_app.config["EXPORT_FOLDER"],
        original_filename=uploaded_file.filename,
        source_language=source_language,
        target_language=target_language,
        max_workers=current_app.config["TRANSLATION_MAX_WORKERS"],
        preview_limit=current_app.config["TRANSLATION_PREVIEW_PAGES"],
        enable_ocr=current_app.config["ENABLE_OCR"],
        tesseract_cmd=current_app.config["TESSERACT_CMD"],
        ocr_languages=current_app.config["OCR_LANGUAGES"],
        glossary_path=current_app.config["GLOSSARY_PATH"],
    )

    return (
        jsonify(
            {
                "ok": True,
                "message": "Ceviri baslatildi.",
                "data": {
                    "job_id": job.job_id,
                    "status_url": f"/jobs/{job.job_id}",
                },
            }
        ),
        202,
    )


@web_bp.get("/jobs/<job_id>")
def job_status(job_id: str):
    job = job_store.serialize_job(job_id)
    if job is None:
        return jsonify({"ok": False, "message": "Islem bulunamadi."}), 404

    return jsonify({"ok": True, "data": job})


@web_bp.get("/downloads/<path:filename>")
def download_export(filename: str):
    export_folder = Path(current_app.config["EXPORT_FOLDER"])
    return send_from_directory(export_folder, filename, as_attachment=True)
