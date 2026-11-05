from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from werkzeug.utils import secure_filename


def is_allowed_file(filename: str, allowed_extensions: set[str]) -> bool:
    if "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in allowed_extensions


def build_unique_upload_path(filename: str, upload_folder: Path) -> Path:
    safe_name = secure_filename(filename)
    stem = Path(safe_name).stem or "document"
    suffix = Path(safe_name).suffix or ".pdf"
    return upload_folder / f"{stem}-{uuid4().hex[:12]}{suffix}"
