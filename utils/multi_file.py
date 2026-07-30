"""
Support for ZIP archives containing one or more datasets.

Flow: user uploads a .zip -> we extract it into a scratch folder -> list the
supported files inside (with size) -> the user picks one -> it goes through
the normal load/clean/profile/store pipeline, same as any single-file upload.

We deliberately do NOT auto-merge multiple files with different schemas -
silently concatenating unrelated tables produces nonsense analytics. If a
user wants to combine files, they analyze one, then upload the next.
"""
from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path

from config import Config

SUPPORTED_EXTS = {"csv", "xlsx", "xls", "json", "tsv", "txt"}
MAX_FILES_LISTED = 25


class ZipExtractionError(Exception):
    pass


def extract_zip_archive(zip_path: Path) -> tuple[str, list[dict]]:
    """
    Extracts a zip file into a scratch directory under uploads/_zips/<batch_id>/.
    Returns (batch_id, [{name, size_kb, relative_path}, ...]) for supported files.
    """
    batch_id = uuid.uuid4().hex[:12]
    extract_dir = Config.UPLOAD_DIR / "_zips" / batch_id
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            # Guard against zip bombs / path traversal before extracting anything
            total_uncompressed = sum(info.file_size for info in zf.infolist())
            if total_uncompressed > Config.MAX_CONTENT_LENGTH * 5:
                raise ZipExtractionError("This archive is too large once uncompressed.")
            for info in zf.infolist():
                if info.filename.startswith("/") or ".." in Path(info.filename).parts:
                    raise ZipExtractionError("Archive contains unsafe file paths.")
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise ZipExtractionError("This doesn't look like a valid .zip file.") from exc

    files = []
    for path in sorted(extract_dir.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            ext = path.suffix.lower().lstrip(".")
            if ext in SUPPORTED_EXTS:
                files.append({
                    "name": path.name,
                    "relative_path": str(path.relative_to(extract_dir)),
                    "size_kb": round(path.stat().st_size / 1024, 1),
                })
        if len(files) >= MAX_FILES_LISTED:
            break

    if not files:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise ZipExtractionError(
            "No supported files (.csv, .xlsx, .xls, .json, .tsv, .txt) were found in this archive."
        )

    return batch_id, files


def resolve_batch_file(batch_id: str, relative_path: str) -> Path:
    extract_dir = Config.UPLOAD_DIR / "_zips" / batch_id
    target = (extract_dir / relative_path).resolve()
    if extract_dir.resolve() not in target.parents and target != extract_dir.resolve():
        raise ZipExtractionError("Invalid file selection.")
    if not target.exists():
        raise ZipExtractionError("That file is no longer available - please re-upload the archive.")
    return target


def cleanup_batch(batch_id: str) -> None:
    extract_dir = Config.UPLOAD_DIR / "_zips" / batch_id
    shutil.rmtree(extract_dir, ignore_errors=True)
