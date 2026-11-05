from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 20 * 1024 * 1024))
    UPLOAD_FOLDER = BASE_DIR / "uploads"
    EXPORT_FOLDER = BASE_DIR / "exports"
    ALLOWED_EXTENSIONS = {"pdf"}
    DEFAULT_SOURCE_LANGUAGE = os.getenv("DEFAULT_SOURCE_LANGUAGE", "auto")
    DEFAULT_TARGET_LANGUAGE = os.getenv("DEFAULT_TARGET_LANGUAGE", "en")
    APP_NAME = os.getenv("APP_NAME", "PDF Translate Studio")
    TRANSLATION_MAX_WORKERS = int(os.getenv("TRANSLATION_MAX_WORKERS", "6"))
    TRANSLATION_PREVIEW_PAGES = int(os.getenv("TRANSLATION_PREVIEW_PAGES", "8"))
    ENABLE_OCR = os.getenv("ENABLE_OCR", "true").lower() == "true"
    OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "tur+eng")
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")
    GLOSSARY_PATH = BASE_DIR / "app" / "data" / "glossary.json"
    TRANSLATION_PROVIDER = os.getenv("TRANSLATION_PROVIDER", "argos")
    LIBRETRANSLATE_URL = os.getenv(
        "LIBRETRANSLATE_URL",
        "https://libretranslate.com/translate",
    )
    LIBRETRANSLATE_API_KEY = os.getenv("LIBRETRANSLATE_API_KEY", "")
