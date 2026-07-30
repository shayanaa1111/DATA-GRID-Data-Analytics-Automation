"""
Auto-detects file type from its extension/content and loads it into a
pandas DataFrame. This is the single entry point the rest of the app uses
to turn "a file on disk" into "a DataFrame" without caring what format it
started as.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

import pandas as pd


class UnsupportedFileError(Exception):
    pass


def load_dataset(filepath: str | Path) -> Tuple[pd.DataFrame, str]:
    """
    Load a dataset from disk into a DataFrame.

    Returns (dataframe, detected_format).
    Raises UnsupportedFileError if the format can't be handled.
    """
    filepath = Path(filepath)
    ext = filepath.suffix.lower().lstrip(".")

    try:
        if ext == "csv":
            df = _read_delimited(filepath, sep=",")
            return df, "csv"

        if ext == "tsv":
            df = _read_delimited(filepath, sep="\t")
            return df, "tsv"

        if ext == "txt":
            # Sniff the delimiter for plain text exports
            sep = _sniff_delimiter(filepath)
            df = _read_delimited(filepath, sep=sep)
            return df, "txt"

        if ext in ("xlsx", "xls"):
            df = pd.read_excel(filepath, sheet_name=0)
            return df, "excel"

        if ext == "json":
            df = _read_json(filepath)
            return df, "json"

        raise UnsupportedFileError(f"'.{ext}' files are not supported yet.")

    except UnsupportedFileError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a clean message upstream
        raise UnsupportedFileError(f"Could not read this file as .{ext}: {exc}") from exc


def _read_delimited(filepath: Path, sep: str) -> pd.DataFrame:
    # The C engine is dramatically faster than the Python engine on large
    # files (often 10-50x), so it's the default path. We only fall back to
    # the slower, more lenient Python engine if the fast path can't handle
    # this specific file (e.g. inconsistent column counts row-to-row).
    last_error = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(filepath, sep=sep, encoding=encoding, engine="c", low_memory=False)
        except UnicodeDecodeError:
            continue
        except pd.errors.ParserError as exc:
            last_error = exc
            break  # this encoding read fine; it's a structural issue, not an encoding one

    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(filepath, sep=sep, encoding=encoding, engine="python", on_bad_lines="skip")
        except UnicodeDecodeError:
            continue
        except pd.errors.ParserError as exc:
            last_error = exc

    if last_error:
        raise last_error
    # last resort, let pandas raise its own clean error
    return pd.read_csv(filepath, sep=sep, engine="python")


def _sniff_delimiter(filepath: Path) -> str:
    with open(filepath, "r", errors="ignore") as f:
        sample = f.readline()
    counts = {d: sample.count(d) for d in (",", "\t", ";", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _read_json(filepath: Path) -> pd.DataFrame:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return pd.json_normalize(data)
    if isinstance(data, dict):
        # Common shapes: {"data": [...]}, {"records": [...]}, or a single record
        for key in ("data", "records", "results", "rows", "items"):
            if key in data and isinstance(data[key], list):
                return pd.json_normalize(data[key])
        return pd.json_normalize([data])
    raise UnsupportedFileError("JSON file must contain an object or array of records.")


def allowed_file(filename: str, allowed_extensions: set[str]) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions
