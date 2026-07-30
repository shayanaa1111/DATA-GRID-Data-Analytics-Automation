"""
Lightweight on-disk persistence for processed datasets.

Each uploaded dataset gets a UUID. We store the raw file, the cleaned
DataFrame (pickle, fast round-trip of dtypes), and its profile/metadata
(JSON) under processed_data/<dataset_id>/. A Flask session just remembers
the dataset_id, so the app works fine with multiple users/tabs without a
real database.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import pandas as pd

from config import Config


def dataset_dir(dataset_id: str) -> Path:
    d = Config.PROCESSED_DIR / dataset_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_dataset(dataset_id: str, raw_df: pd.DataFrame, clean_df: pd.DataFrame,
                  cleaning_log: list[str], profile: dict, meta: dict) -> None:
    d = dataset_dir(dataset_id)
    with open(d / "raw.pkl", "wb") as f:
        pickle.dump(raw_df, f)
    with open(d / "clean.pkl", "wb") as f:
        pickle.dump(clean_df, f)
    with open(d / "meta.json", "w") as f:
        json.dump({
            "cleaning_log": cleaning_log,
            "profile": profile,
            **meta,
        }, f, default=str)


def load_clean_df(dataset_id: str) -> pd.DataFrame:
    with open(dataset_dir(dataset_id) / "clean.pkl", "rb") as f:
        return pickle.load(f)


def load_raw_df(dataset_id: str) -> pd.DataFrame:
    with open(dataset_dir(dataset_id) / "raw.pkl", "rb") as f:
        return pickle.load(f)


def load_meta(dataset_id: str) -> dict:
    with open(dataset_dir(dataset_id) / "meta.json", "r") as f:
        return json.load(f)


def update_meta(dataset_id: str, patch: dict) -> dict:
    meta = load_meta(dataset_id)
    meta.update(patch)
    with open(dataset_dir(dataset_id) / "meta.json", "w") as f:
        json.dump(meta, f, default=str)
    return meta


def dataset_exists(dataset_id: str) -> bool:
    return (Config.PROCESSED_DIR / dataset_id / "meta.json").exists()


def toggle_pin(dataset_id: str) -> bool:
    """Flips the pinned flag for a dataset and returns the new state."""
    meta = load_meta(dataset_id)
    new_state = not meta.get("pinned", False)
    update_meta(dataset_id, {"pinned": new_state})
    return new_state


def list_pinned_datasets() -> list[dict]:
    entries = []
    if not Config.PROCESSED_DIR.exists():
        return entries
    for d in Config.PROCESSED_DIR.iterdir():
        meta_file = d / "meta.json"
        if not meta_file.exists():
            continue
        try:
            with open(meta_file) as f:
                meta = json.load(f)
            if meta.get("pinned"):
                entries.append({
                    "dataset_id": d.name,
                    "filename": meta.get("filename", "dataset"),
                    "rows": meta.get("profile", {}).get("shape", {}).get("rows"),
                    "columns": meta.get("profile", {}).get("shape", {}).get("columns"),
                })
        except (json.JSONDecodeError, OSError):
            continue
    return entries


def list_recent_datasets(limit: int = 5) -> list[dict]:
    entries = []
    if not Config.PROCESSED_DIR.exists():
        return entries
    dirs = sorted(
        Config.PROCESSED_DIR.iterdir(),
        key=lambda p: p.stat().st_mtime if p.is_dir() else 0,
        reverse=True,
    )
    for d in dirs:
        meta_file = d / "meta.json"
        if meta_file.exists():
            try:
                with open(meta_file) as f:
                    meta = json.load(f)
                entries.append({
                    "dataset_id": d.name,
                    "filename": meta.get("filename", "dataset"),
                    "rows": meta.get("profile", {}).get("shape", {}).get("rows"),
                    "columns": meta.get("profile", {}).get("shape", {}).get("columns"),
                    "uploaded_at": meta.get("uploaded_at"),
                })
            except (json.JSONDecodeError, OSError):
                continue
        if len(entries) >= limit:
            break
    return entries
