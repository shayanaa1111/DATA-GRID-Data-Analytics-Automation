"""
Shared statistical helpers + KPI card generation for dataset analytics.

Server-rendered chart *images* (histograms, box plots, correlation
heatmaps, etc.) live in utils/chart_images.py, which imports several
helpers from this module (_is_identifier_column, _metric_columns,
_sample_values, _top_correlation_pairs, _prettify). Chart rendering was
moved off a client-side JS library (previously Plotly.js via CDN) to
matplotlib/seaborn precisely so the core EDA experience has zero external
network dependency and can't be broken by a blocked CDN, ad-blocker, or
offline browser.

This is intentionally generic: it never assumes a specific schema, since
the platform must handle *any* uploaded dataset.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

KPI_KEYWORDS = [
    "revenue", "sales", "profit", "amount", "price", "cost", "total",
    "quantity", "qty", "orders", "customers", "users", "inventory", "stock",
    "score", "rating", "population", "attendance", "salary", "income",
    "expense", "budget", "count", "units", "value",
]

PALETTE = ["#22D3B8", "#4F8EF7", "#F5A623", "#F76E6E", "#B18CFF", "#3DD9C2"]

ID_NAME_PATTERN = ["_id", "id_", "uuid", "index", "unnamed"]


def _is_identifier_column(df: pd.DataFrame, col: str) -> bool:
    """ID-like columns (order_id, customer_id, row index...) are unique keys,
    not business metrics — charting/summing them is meaningless, so we keep
    them out of KPI cards, histograms, and time-series aggregation."""
    name = col.lower()
    if name == "id" or any(p in name for p in ID_NAME_PATTERN):
        return True
    series = df[col].dropna()
    if series.empty:
        return False
    # Near-unique INTEGER columns are almost always keys (e.g. order_id).
    # Continuous float metrics (revenue, profit...) are legitimately
    # near-unique too, so this check only applies to integer dtypes.
    if pd.api.types.is_integer_dtype(series):
        return series.nunique() / len(series) > 0.98
    return False


def _json_safe(value):
    """Recursively strips NaN/Infinity from any nested dict/list/number
    structure, replacing them with None (renders as `null`).

    This matters because Python's json.dumps (which Jinja's |tojson filter
    and Flask's jsonify both use) happily emits bare `NaN`/`Infinity`
    tokens by default — valid Python, but NOT valid JSON. Browsers'
    JSON.parse is strict and throws on them, which silently breaks the
    *entire* chart payload (one bad float anywhere poisons the whole
    parse). NaN shows up more often than you'd think: correlating a
    constant/zero-variance column produces NaN, as does dividing by a
    zero mean for coefficient of variation, etc. Every chart/KPI builder
    routes its return value through this before it reaches a template.
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (float, np.floating)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


def _metric_columns(df: pd.DataFrame, numeric_cols: list[str]) -> list[str]:
    return [c for c in numeric_cols if not _is_identifier_column(df, c)]


def _sample_values(series: pd.Series, max_points: int = 5000, seed: int = 0) -> tuple[list[float], bool, int]:
    """Bounds how many raw values get sent to the browser for point-heavy
    chart types (box, violin, scatter matrix). Returns (values, was_sampled,
    original_count). A fixed seed keeps results stable across repeated
    dashboard loads of the same dataset (cache-friendly, reproducible)."""
    total = len(series)
    if total <= max_points:
        return series.tolist(), False, total
    sampled = series.sample(n=max_points, random_state=seed)
    return sampled.tolist(), True, total


def build_kpi_cards(df: pd.DataFrame, max_cards: int = 8) -> list[dict]:
    numeric_cols = _metric_columns(df, df.select_dtypes(include=np.number).columns.tolist())
    cards = []

    # Always-present structural KPIs first
    cards.append({"label": "Total Records", "value": int(df.shape[0]), "format": "int", "icon": "database",
                   "trend": [], "growth_pct": None, "direction": "flat"})
    cards.append({"label": "Columns", "value": int(df.shape[1]), "format": "int", "icon": "columns",
                   "trend": [], "growth_pct": None, "direction": "flat"})

    matched = [c for c in numeric_cols if any(k in c.lower() for k in KPI_KEYWORDS)]
    remaining_slots = max_cards - len(cards)

    datetime_cols = df.select_dtypes(include="datetime").columns.tolist()
    ordered_df = df.sort_values(datetime_cols[0]) if datetime_cols else df

    for col in matched[:remaining_slots]:
        series = df[col].dropna()
        if series.empty:
            continue
        trend, growth, direction = _compute_trend(ordered_df[col])
        cards.append({
            "label": _prettify(col) + " (Total)",
            "value": _safe_round(series.sum()),
            "format": "number",
            "icon": "trending-up",
            "trend": trend, "growth_pct": growth, "direction": direction,
        })
        if len(cards) >= max_cards:
            break
        cards.append({
            "label": _prettify(col) + " (Avg)",
            "value": _safe_round(series.mean()),
            "format": "number",
            "icon": "activity",
            "trend": trend, "growth_pct": growth, "direction": direction,
        })

    return _json_safe(cards[:max_cards])


def _compute_trend(series: pd.Series, buckets: int = 8) -> tuple[list[float], float | None, str]:
    """Splits a metric column into ordered buckets (chronological if the
    caller pre-sorted by date, otherwise row order) and returns a small
    sparkline series + overall growth % between the first and last bucket.
    Works even without a datetime column, since row order is still a
    meaningful sequence for most tabular exports."""
    clean = series.dropna()
    if len(clean) < 4:
        return [], None, "flat"
    chunks = np.array_split(clean.values, min(buckets, len(clean)))
    points = [_safe_round(float(np.mean(c)), 4) for c in chunks if len(c)]
    if len(points) < 2:
        return points, None, "flat"
    first, last = points[0], points[-1]
    if first == 0:
        growth = None
    else:
        growth = round(((last - first) / abs(first)) * 100, 1)
    direction = "flat"
    if growth is not None:
        direction = "up" if growth > 1 else ("down" if growth < -1 else "flat")
    return points, growth, direction


def _top_correlation_pairs(corr: pd.DataFrame, top_n: int = 8) -> list[dict]:
    pairs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            val = corr.iloc[i, j]
            if pd.isna(val):
                continue
            pairs.append({"label": f"{_prettify(cols[i])} vs {_prettify(cols[j])}", "value": round(float(val), 2)})
    pairs.sort(key=lambda p: abs(p["value"]), reverse=True)
    return pairs[:top_n]



def _prettify(col: str) -> str:
    return str(col).replace("_", " ").title()


def _safe_round(value, digits=2):
    if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
        return 0
    return round(float(value), digits)
