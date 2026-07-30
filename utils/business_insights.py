"""
Deterministic business insights computed straight from pandas — no AI call
required, so these are available immediately on every dashboard load. The
AI Executive Summary (services/ai_service.py) is a complementary, richer
narrative layered on top of these hard numbers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from utils.charts import _is_identifier_column, _prettify


def build_business_insights(df: pd.DataFrame) -> dict:
    numeric_cols = [c for c in df.select_dtypes(include=np.number).columns if not _is_identifier_column(df, c)]
    categorical_cols = [
        c for c in df.select_dtypes(include="object").columns
        if 1 < df[c].nunique(dropna=True) <= 30
        and not any(p in c.lower() for p in ["_id", "id_", "uuid", "name", "email", "phone", "address"])
    ]

    result = {
        "top_performers": [],
        "bottom_performers": [],
        "risk_indicators": [],
        "growth_opportunities": [],
    }

    if numeric_cols and categorical_cols:
        metric = numeric_cols[0]
        cat = categorical_cols[0]

        grouped = df.groupby(cat, dropna=True)[metric].agg(["sum", "mean", "count"]).sort_values("sum", ascending=False)
        grouped = grouped[grouped["count"] >= 2]  # ignore one-off categories, too noisy to call a "performer"

        if not grouped.empty:
            top = grouped.head(3)
            bottom = grouped.tail(3).sort_values("sum")
            total = grouped["sum"].sum()

            result["top_performers"] = [
                {
                    "label": str(idx), "dimension": _prettify(cat), "metric": _prettify(metric),
                    "value": round(float(row["sum"]), 2),
                    "share_pct": round(100 * float(row["sum"]) / total, 1) if total else 0,
                }
                for idx, row in top.iterrows()
            ]
            result["bottom_performers"] = [
                {
                    "label": str(idx), "dimension": _prettify(cat), "metric": _prettify(metric),
                    "value": round(float(row["sum"]), 2),
                    "share_pct": round(100 * float(row["sum"]) / total, 1) if total else 0,
                }
                for idx, row in bottom.iterrows()
            ]

            # Growth opportunity heuristic: categories with a healthy average
            # value per record but a below-median record count — currently
            # under-represented in volume relative to how well they perform.
            median_count = grouped["count"].median()
            candidates = grouped[grouped["count"] <= median_count].sort_values("mean", ascending=False).head(3)
            result["growth_opportunities"] = [
                {
                    "label": str(idx), "dimension": _prettify(cat),
                    "reason": f"High average {_prettify(metric)} ({row['mean']:.2f}) but only {int(row['count'])} "
                              f"records — scaling this segment could lift overall {_prettify(metric)}.",
                }
                for idx, row in candidates.iterrows()
            ]

            top_share = grouped["sum"].iloc[0] / total if total else 0
            if top_share > 0.5:
                result["risk_indicators"].append({
                    "type": "concentration",
                    "message": f"{grouped.index[0]} accounts for {top_share * 100:.0f}% of total {_prettify(metric)} — "
                                "high concentration risk if that segment declines.",
                })

    # Risk indicators: data-quality issues, always deterministic
    missing_pct = df.isna().mean().sort_values(ascending=False)
    worst_missing = missing_pct[missing_pct > 0.15].head(3)
    for col, pct in worst_missing.items():
        result["risk_indicators"].append({
            "type": "data_quality",
            "message": f"{_prettify(col)} is missing in {pct * 100:.1f}% of rows — treat metrics involving it with caution.",
        })

    dup_pct = df.duplicated().mean()
    if dup_pct > 0.05:
        result["risk_indicators"].append({
            "type": "duplicates",
            "message": f"{dup_pct * 100:.1f}% of rows are duplicates even after cleaning — verify the source export.",
        })

    return result
