"""
Automatic data cleaning.

clean_dataset() takes a raw DataFrame and returns:
  - the cleaned DataFrame
  - a list of human-readable log entries describing exactly what was
    changed and why, so the Data Cleaning page can show a transparent
    before/after trail instead of a black box.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class CleaningLog:
    steps: list[str] = field(default_factory=list)

    def add(self, message: str):
        self.steps.append(message)


def clean_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    log = CleaningLog()
    df = df.copy()
    original_shape = df.shape

    df = _clean_column_names(df, log)
    df = _strip_whitespace(df, log)
    df = _drop_empty_rows_cols(df, log)
    df = _drop_duplicate_rows(df, log)
    df = _drop_duplicate_columns(df, log)
    df = _fix_dtypes(df, log)
    df = _standardize_missing_tokens(df, log)
    df = _handle_missing_values(df, log)
    df = _flag_outliers(df, log)

    log.add(
        f"Finished cleaning: {original_shape[0]} rows x {original_shape[1]} cols "
        f"-> {df.shape[0]} rows x {df.shape[1]} cols."
    )
    return df, log.steps


def _clean_column_names(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    original = list(df.columns)
    new_cols = []
    for col in original:
        clean = str(col).strip()
        clean = re.sub(r"\s+", "_", clean)
        clean = re.sub(r"[^\w]", "_", clean)
        clean = re.sub(r"_+", "_", clean).strip("_").lower()
        new_cols.append(clean or "column")
    # de-duplicate any collisions created by normalization
    seen = {}
    deduped = []
    for c in new_cols:
        if c in seen:
            seen[c] += 1
            deduped.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            deduped.append(c)
    df.columns = deduped
    if deduped != original:
        log.add("Standardized column names to lowercase snake_case.")
    return df


def _strip_whitespace(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    obj_cols = df.select_dtypes(include="object").columns
    changed = False
    for col in obj_cols:
        stripped = df[col].astype(str).str.strip()
        if not stripped.equals(df[col].astype(str)):
            changed = True
        df[col] = df[col].where(df[col].isna(), stripped)
    if changed:
        log.add("Removed leading/trailing whitespace from text columns.")
    return df


def _drop_empty_rows_cols(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    before_rows, before_cols = df.shape
    df = df.dropna(axis=0, how="all")
    df = df.dropna(axis=1, how="all")
    if df.shape[0] != before_rows:
        log.add(f"Removed {before_rows - df.shape[0]} completely empty row(s).")
    if df.shape[1] != before_cols:
        log.add(f"Removed {before_cols - df.shape[1]} completely empty column(s).")
    return df


def _drop_duplicate_rows(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates()
    removed = before - len(df)
    if removed:
        log.add(f"Removed {removed} duplicate row(s).")
    return df.reset_index(drop=True)


def _drop_duplicate_columns(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Finds columns with identical values using per-column hashing instead
    of df.T.duplicated(). Transposing scales with row count (an 8-column x
    300,000-row frame becomes a 300,000-column transposed frame — brutally
    slow); hashing each column is O(rows x cols) done column-wise, the way
    it should be, and is fast even on very large datasets."""
    seen_hashes: dict[int, list[str]] = {}
    dropped = []
    keep_mask = []
    for col in df.columns:
        h = int(pd.util.hash_pandas_object(df[col], index=False).sum())
        group = seen_hashes.setdefault(h, [])
        is_dupe = any(df[col].equals(df[other]) for other in group)
        if is_dupe:
            dropped.append(col)
            keep_mask.append(False)
        else:
            group.append(col)
            keep_mask.append(True)

    if dropped:
        df = df.loc[:, keep_mask]
        log.add(f"Removed {len(dropped)} duplicate column(s): {', '.join(dropped)}.")
    return df


def _standardize_missing_tokens(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    tokens = {"na", "n/a", "null", "none", "-", "--", "?", "unknown", ""}
    obj_cols = df.select_dtypes(include="object").columns
    touched = False
    for col in obj_cols:
        mask = df[col].astype(str).str.strip().str.lower().isin(tokens)
        if mask.any():
            df.loc[mask, col] = np.nan
            touched = True
    if touched:
        log.add("Standardized placeholder text (e.g. 'N/A', 'null', '-') to proper missing values.")
    return df


def _fix_dtypes(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    converted_numeric, converted_date = [], []
    for col in df.select_dtypes(include="object").columns:
        sample = df[col].dropna().astype(str).head(200)
        if sample.empty:
            continue

        # Try numeric (handles things like "$1,200.50" or "12%")
        cleaned = sample.str.replace(r"[,$%]", "", regex=True).str.strip()
        numeric_ratio = pd.to_numeric(cleaned, errors="coerce").notna().mean()
        if numeric_ratio > 0.9:
            full_clean = df[col].astype(str).str.replace(r"[,$%]", "", regex=True).str.strip()
            df[col] = pd.to_numeric(full_clean, errors="coerce")
            converted_numeric.append(col)
            continue

        # Try datetime
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
        if parsed.notna().mean() > 0.9:
            df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")
            converted_date.append(col)

    if converted_numeric:
        log.add(f"Converted text to numeric for: {', '.join(converted_numeric)}.")
    if converted_date:
        log.add(f"Converted text to datetime for: {', '.join(converted_date)}.")
    return df


def _handle_missing_values(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    numeric_cols = df.select_dtypes(include=np.number).columns
    cat_cols = df.select_dtypes(include="object").columns

    filled_numeric, filled_cat = [], []
    for col in numeric_cols:
        n_missing = df[col].isna().sum()
        if n_missing and n_missing / len(df) < 0.5:  # don't fabricate data for mostly-empty columns
            df[col] = df[col].fillna(df[col].median())
            filled_numeric.append(col)

    for col in cat_cols:
        n_missing = df[col].isna().sum()
        if n_missing and n_missing / len(df) < 0.5:
            mode = df[col].mode(dropna=True)
            fill_val = mode.iloc[0] if not mode.empty else "Unknown"
            df[col] = df[col].fillna(fill_val)
            filled_cat.append(col)

    if filled_numeric:
        log.add(f"Filled missing numeric values with the column median for: {', '.join(filled_numeric)}.")
    if filled_cat:
        log.add(f"Filled missing categorical values with the most common value for: {', '.join(filled_cat)}.")
    return df


def _flag_outliers(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """We flag outliers for visibility but do NOT silently delete them —
    removing real data points without the user's say-so is dangerous for
    business analytics. The Data Profiling page surfaces the count."""
    numeric_cols = df.select_dtypes(include=np.number).columns
    total_outliers = 0
    for col in numeric_cols:
        q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        total_outliers += int(((df[col] < lower) | (df[col] > upper)).sum())
    if total_outliers:
        log.add(
            f"Detected {total_outliers} statistical outlier value(s) using the IQR method "
            "(kept in the data, flagged for review in Data Profiling)."
        )
    return df
