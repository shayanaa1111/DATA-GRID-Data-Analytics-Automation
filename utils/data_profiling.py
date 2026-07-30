"""
Builds the data profile shown on the Data Profiling page and used to power
KPI selection and chart generation elsewhere in the app.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def profile_dataset(df: pd.DataFrame) -> dict:
    numeric_cols = df.select_dtypes(include=np.number).columns.tolist()
    datetime_cols = df.select_dtypes(include="datetime").columns.tolist()
    categorical_cols = [c for c in df.columns if c not in numeric_cols and c not in datetime_cols]

    profile = {
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "memory_usage_mb": round(df.memory_usage(deep=True).sum() / (1024 * 1024), 3),
        "duplicate_rows": int(df.duplicated().sum()),
        "column_types": {
            "numeric": len(numeric_cols),
            "categorical": len(categorical_cols),
            "datetime": len(datetime_cols),
        },
        "columns": [],
        "numeric_summary": {},
        "categorical_summary": {},
        "datetime_summary": {},
    }

    total_cells = df.shape[0] * df.shape[1] or 1
    total_missing = int(df.isna().sum().sum())

    for col in df.columns:
        series = df[col]
        n_missing = int(series.isna().sum())
        n_unique = int(series.nunique(dropna=True))
        col_info = {
            "name": col,
            "dtype": str(series.dtype),
            "missing_count": n_missing,
            "missing_pct": round(100 * n_missing / len(df), 2) if len(df) else 0,
            "unique_count": n_unique,
            "cardinality_pct": round(100 * n_unique / len(df), 2) if len(df) else 0,
        }
        profile["columns"].append(col_info)

        if col in numeric_cols:
            desc = series.describe()
            mean_val = desc.get("mean")
            std_val = desc.get("std")
            cv = (std_val / mean_val) if mean_val not in (0, None) and not pd.isna(mean_val) and std_val is not None else None
            profile["numeric_summary"][col] = {
                "mean": _safe_round(mean_val),
                "median": _safe_round(series.median()),
                "std": _safe_round(std_val),
                "min": _safe_round(desc.get("min")),
                "max": _safe_round(desc.get("max")),
                "p05": _safe_round(series.quantile(0.05)),
                "p10": _safe_round(series.quantile(0.10)),
                "q1": _safe_round(series.quantile(0.25)),
                "q3": _safe_round(series.quantile(0.75)),
                "p90": _safe_round(series.quantile(0.90)),
                "p95": _safe_round(series.quantile(0.95)),
                "skewness": _safe_round(series.skew()),
                "kurtosis": _safe_round(series.kurt()),
                "coefficient_of_variation": _safe_round(cv),
            }
        elif col in datetime_cols:
            valid = series.dropna()
            profile["datetime_summary"][col] = {
                "min": str(valid.min()) if not valid.empty else None,
                "max": str(valid.max()) if not valid.empty else None,
                "range_days": int((valid.max() - valid.min()).days) if not valid.empty else None,
            }
        else:
            value_counts = series.value_counts(dropna=True).head(5)
            profile["categorical_summary"][col] = {
                "top_values": [{"value": str(k), "count": int(v)} for k, v in value_counts.items()],
                "unique_count": n_unique,
            }

    # Simple, explainable quality score: penalize missingness and duplicate rows
    missing_pct = 100 * total_missing / total_cells
    dup_pct = 100 * profile["duplicate_rows"] / (len(df) or 1)
    quality_score = max(0, round(100 - (missing_pct * 0.6) - (dup_pct * 0.4), 1))
    profile["quality_score"] = quality_score
    profile["total_missing_cells"] = total_missing
    profile["total_missing_pct"] = round(missing_pct, 2)

    return profile


def _safe_round(value, digits=3):
    if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
        return None
    return round(float(value), digits)
