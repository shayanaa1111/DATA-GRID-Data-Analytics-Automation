"""
Lightweight "dataset intelligence": heuristic, deterministic signals about
what kind of dataset this is and what's worth paying attention to. No AI
call required — this runs instantly on every dashboard load and can inform
what the AI is told (or what a person skims before diving in).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from services.prompts import DOMAIN_KEYWORDS
from utils.charts import KPI_KEYWORDS, _is_identifier_column


def analyze_dataset(df: pd.DataFrame) -> dict:
    columns_lower = [c.lower() for c in df.columns]

    domain, domain_score = _detect_domain(columns_lower)
    kpi_candidates = _detect_kpi_candidates(df)
    anomaly_summary = _detect_anomalies(df)
    key_candidates = _detect_key_candidates(df)

    return {
        "business_domain": domain,
        "domain_confidence": domain_score,
        "kpi_candidates": kpi_candidates,
        "anomaly_summary": anomaly_summary,
        "key_candidates": key_candidates,
    }


def _detect_domain(columns_lower: list[str]) -> tuple[str, float]:
    best_domain, best_score = "General / Unclassified", 0
    for domain, keywords in DOMAIN_KEYWORDS.items():
        hits = sum(1 for kw in keywords if any(kw in col for col in columns_lower))
        if hits > best_score:
            best_domain, best_score = domain, hits
    if best_score == 0:
        return "General / Unclassified", 0.0
    confidence = round(min(1.0, best_score / 3), 2)  # 3+ keyword hits = full confidence
    return best_domain, confidence


def _detect_kpi_candidates(df: pd.DataFrame) -> list[str]:
    numeric_cols = [c for c in df.select_dtypes(include=np.number).columns if not _is_identifier_column(df, c)]
    return [c for c in numeric_cols if any(k in c.lower() for k in KPI_KEYWORDS)][:10]


def _detect_anomalies(df: pd.DataFrame) -> dict:
    numeric_cols = [c for c in df.select_dtypes(include=np.number).columns if not _is_identifier_column(df, c)]
    per_column = {}
    total = 0
    for col in numeric_cols:
        series = df[col].dropna()
        if series.empty:
            continue
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        count = int(((series < lower) | (series > upper)).sum())
        if count:
            per_column[col] = count
            total += count
    return {"total_anomalies": total, "by_column": per_column}


def _detect_key_candidates(df: pd.DataFrame) -> list[str]:
    """Columns that look like they could be a primary/foreign key — useful
    context for anyone about to join this dataset against another one."""
    candidates = []
    for col in df.columns:
        name = col.lower()
        if name == "id" or name.endswith("_id") or name.endswith("id"):
            candidates.append(col)
    return candidates[:10]
