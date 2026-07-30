"""
Server-side chart rendering for the Exploratory Data Analysis tab (and, via
render_query_chart(), for SQL Analytics result charting too).

Every chart is drawn with matplotlib/seaborn (Agg backend, no display
needed) and returned as a base64-encoded PNG, embedded directly in the
HTML/JSON as a data URI. This is a deliberate alternative to client-side
JS charting libraries (Plotly, Chart.js, etc): it has ZERO external network
requests and ZERO client-side charting dependency, so it cannot be broken
by a blocked CDN, an ad-blocker, a corporate firewall, or an offline
browser — if the page loaded at all, these charts are already part of it.

The tradeoff is losing interactivity (hover tooltips, client-side zoom,
pan). Given how often "my charts won't render" turns out to be a
third-party script getting blocked, that tradeoff is the right default for
a dashboard whose whole job is "just show me the data."
"""
from __future__ import annotations

import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from utils.charts import _is_identifier_column, _prettify, _sample_values, _top_correlation_pairs

# Palette + dark theme to match the app's CSS variables (static/css/style.css)
BG = "#111a2c"          # --surface
GRID = "#223050"         # --border
TEXT = "#c3cbdb"          # readable light gray on dark bg
MUTED = "#8b98b3"          # --text-muted
PALETTE = ["#22d3b8", "#4f8ef7", "#e8951f", "#e05c5c", "#8a6fd4", "#3dd9c2"]

sns.set_theme(style="darkgrid", rc={
    "figure.facecolor": BG,
    "axes.facecolor": BG,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.alpha": 0.6,
    "text.color": TEXT,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "font.size": 10,
    "font.family": "sans-serif",
})

MAX_CHART_POINTS = 5000  # matches the sampling threshold previously used for the Plotly path


def build_dashboard_chart_images(df: pd.DataFrame) -> list[dict]:
    """Returns [{id, title, category, sampled, sample_size, total_size, image_base64}, ...]."""
    charts = []
    all_numeric_cols = df.select_dtypes(include=np.number).columns.tolist()
    numeric_cols = [c for c in all_numeric_cols if not _is_identifier_column(df, c)]
    categorical_cols = [
        c for c in df.select_dtypes(include="object").columns
        if 1 < df[c].nunique(dropna=True) <= 20
        and not any(p in c.lower() for p in ["_id", "id_", "uuid", "name", "email", "phone", "address"])
    ]
    datetime_cols = df.select_dtypes(include="datetime").columns.tolist()

    # --- Data quality ---
    missing = df.isna().sum()
    missing = missing[missing > 0].sort_values(ascending=False).head(15)
    if not missing.empty:
        charts.append(_bar_chart(
            "missing_values", "Missing Values by Column", "quality",
            [_prettify(c) for c in missing.index], missing.values, horizontal=True,
            color=PALETTE[3], xlabel="Missing Count",
        ))

    cols_with_missing = df.columns[df.isna().any()].tolist()
    if cols_with_missing:
        sample = df[cols_with_missing].head(200)
        charts.append(_missing_matrix(sample))

    card_data = sorted(((c, df[c].nunique(dropna=True)) for c in df.columns), key=lambda t: t[1], reverse=True)[:15]
    if card_data:
        charts.append(_bar_chart(
            "cardinality", "Unique Value Count by Column", "quality",
            [_prettify(c) for c, _ in card_data], [v for _, v in card_data],
            color=PALETTE[4], ylabel="Unique Values",
        ))

    # --- Distributions ---
    for i, col in enumerate(numeric_cols[:6]):
        series = df[col].dropna()
        if series.empty:
            continue
        charts.append(_histogram(col, series, PALETTE[i % len(PALETTE)]))

    for i, col in enumerate(numeric_cols[:5]):
        series = df[col].dropna()
        if series.empty:
            continue
        charts.append(_box_plot(col, series, PALETTE[i % len(PALETTE)]))

    for i, col in enumerate(numeric_cols[:3]):
        series = df[col].dropna()
        if series.empty or series.nunique() < 3:
            continue
        charts.append(_violin_plot(col, series, PALETTE[i % len(PALETTE)]))

    # --- Categories ---
    for i, col in enumerate(categorical_cols[:4]):
        counts = df[col].value_counts(dropna=True).head(10)
        if counts.empty:
            continue
        charts.append(_bar_chart(
            f"bar_{col}", f"Top {_prettify(col)} Categories", "categories",
            [str(v) for v in counts.index], counts.values, horizontal=True,
            color=PALETTE[(i + 1) % len(PALETTE)], xlabel="Count",
        ))

    if categorical_cols:
        cat_col = categorical_cols[0]
        counts = df[cat_col].value_counts(dropna=True).head(8)
        if not counts.empty:
            charts.append(_donut_chart(cat_col, counts))

    if len(categorical_cols) >= 2:
        stacked = _stacked_bar(df, categorical_cols[0], categorical_cols[1])
        if stacked:
            charts.append(stacked)

    # --- Relationships ---
    if len(numeric_cols) >= 2:
        charts.append(_correlation_heatmap(df, numeric_cols))
        corr = df[numeric_cols].corr(numeric_only=True)
        pairs = _top_correlation_pairs(corr)
        if pairs:
            charts.append(_bar_chart(
                "correlation_ranking", "Strongest Correlations", "relationships",
                [p["label"] for p in pairs], [p["value"] for p in pairs], horizontal=True,
                color=None, colors_list=[PALETTE[0] if p["value"] >= 0 else PALETTE[3] for p in pairs],
                xlabel="Correlation",
            ))

    if len(numeric_cols) >= 2:
        pair_chart = _pair_plot(df, numeric_cols[:4])
        if pair_chart:
            charts.append(pair_chart)

    if len(numeric_cols) >= 3:
        bubble = _bubble_chart(df, numeric_cols[0], numeric_cols[1], numeric_cols[2])
        if bubble:
            charts.append(bubble)

    # --- Time ---
    if datetime_cols and numeric_cols:
        ts_chart = _time_series(df, datetime_cols[0], numeric_cols[0])
        if ts_chart:
            charts.append(ts_chart)
        monthly = _monthly_volume(df, datetime_cols[0])
        if monthly:
            charts.append(monthly)

    return charts


def render_query_chart(columns: list[str], rows: list[list]) -> str | None:
    """Renders a quick bar chart from SQL Analytics query results (first
    column = category axis, first numeric column after it = value axis) and
    returns a base64 PNG, or None if the result shape isn't chartable. Used
    by the 'Chart Results' button in the SQL editor — server-rendered for
    the same reason as the dashboard charts: no client-side library needed."""
    if not rows or not columns:
        return None

    value_idx = None
    for i in range(1, len(columns)):
        if isinstance(rows[0][i], (int, float)) and not isinstance(rows[0][i], bool):
            value_idx = i
            break
    if value_idx is None:
        return None

    labels = [str(r[0]) for r in rows[:30]]
    values = [r[value_idx] if isinstance(r[value_idx], (int, float)) else 0 for r in rows[:30]]

    chart = _bar_chart(
        "query_result", columns[value_idx], "query",
        labels, values, horizontal=True, color=PALETTE[0], xlabel=columns[value_idx],
    )
    return chart["image_base64"]


# --------------------------------------------------------------------------
# Individual chart builders
# --------------------------------------------------------------------------

def _fig(figsize=(6.4, 4.0)):
    fig, ax = plt.subplots(figsize=figsize, dpi=110)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    return fig, ax


def _encode(fig, chart_id, title, category, sampled=False, sample_size=None, total_size=None) -> dict:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "id": chart_id, "title": title, "category": category,
        "sampled": sampled, "sample_size": sample_size, "total_size": total_size,
        "image_base64": b64,
    }


def _bar_chart(chart_id, title, category, labels, values, horizontal=False,
               color=None, colors_list=None, xlabel="", ylabel=""):
    fig, ax = _fig((6.4, max(3.2, 0.32 * len(labels))) if horizontal else (6.4, 4.0))
    bar_colors = colors_list if colors_list else color
    if horizontal:
        ax.barh(list(labels)[::-1], list(values)[::-1], color=bar_colors if not colors_list else list(colors_list)[::-1])
        ax.set_xlabel(xlabel, color=MUTED)
    else:
        ax.bar(list(labels), list(values), color=bar_colors)
        ax.set_ylabel(ylabel, color=MUTED)
        ax.tick_params(axis="x", rotation=35)
    ax.set_title(title, color=TEXT, fontsize=11, pad=10)
    return _encode(fig, chart_id, title, category)


def _histogram(col, series, color):
    fig, ax = _fig()
    sns.histplot(series, bins=30, color=color, ax=ax, edgecolor=BG, linewidth=0.3)
    ax.set_title(f"Distribution of {_prettify(col)}", color=TEXT, fontsize=11, pad=10)
    ax.set_xlabel(_prettify(col), color=MUTED)
    ax.set_ylabel("Frequency", color=MUTED)
    return _encode(fig, f"hist_{col}", f"Distribution of {_prettify(col)}", "distribution")


def _box_plot(col, series, color):
    values, sampled, total = _sample_values(series, max_points=MAX_CHART_POINTS)
    fig, ax = _fig((3.6, 4.6))
    sns.boxplot(y=values, ax=ax, color=color, width=0.35, fliersize=3,
                boxprops={"alpha": 0.85}, flierprops={"markerfacecolor": color, "markeredgecolor": "none", "alpha": 0.6})
    ax.set_title(f"{_prettify(col)} — Outliers", color=TEXT, fontsize=11, pad=10)
    ax.set_ylabel(_prettify(col), color=MUTED)
    return _encode(fig, f"box_{col}", f"{_prettify(col)} — Outlier Detection (Box Plot)", "distribution",
                    sampled=sampled, sample_size=len(values), total_size=total)


def _violin_plot(col, series, color):
    values, sampled, total = _sample_values(series, max_points=MAX_CHART_POINTS)
    fig, ax = _fig((3.6, 4.6))
    sns.violinplot(y=values, ax=ax, color=color, inner="quartile")
    ax.set_title(f"{_prettify(col)} — Shape", color=TEXT, fontsize=11, pad=10)
    ax.set_ylabel(_prettify(col), color=MUTED)
    return _encode(fig, f"violin_{col}", f"{_prettify(col)} — Distribution Shape (Violin)", "distribution",
                    sampled=sampled, sample_size=len(values), total_size=total)


def _donut_chart(cat_col, counts):
    fig, ax = _fig((5.2, 5.2))
    wedges, _ = ax.pie(
        counts.values, labels=None, colors=(PALETTE * 2)[:len(counts)],
        wedgeprops={"width": 0.45, "edgecolor": BG, "linewidth": 1.5},
        startangle=90,
    )
    ax.legend(wedges, [str(v) for v in counts.index], loc="center left",
              bbox_to_anchor=(1.0, 0.5), frameon=False, labelcolor=TEXT, fontsize=9)
    ax.set_title(f"{_prettify(cat_col)} Mix", color=TEXT, fontsize=11, pad=10)
    return _encode(fig, f"donut_{cat_col}", f"{_prettify(cat_col)} Mix", "categories")


def _stacked_bar(df, cat1, cat2):
    top1 = df[cat1].value_counts(dropna=True).head(6).index.tolist()
    top2 = df[cat2].value_counts(dropna=True).head(5).index.tolist()
    sub = df[df[cat1].isin(top1) & df[cat2].isin(top2)]
    if sub.empty:
        return None
    cross = pd.crosstab(sub[cat1], sub[cat2])
    fig, ax = _fig((6.4, 4.4))
    bottom = np.zeros(len(cross))
    for i, col2 in enumerate(cross.columns):
        ax.bar(cross.index.astype(str), cross[col2].values, bottom=bottom,
               label=str(col2), color=PALETTE[i % len(PALETTE)])
        bottom += cross[col2].values
    ax.set_title(f"{_prettify(cat1)} by {_prettify(cat2)} (Stacked)", color=TEXT, fontsize=11, pad=10)
    ax.tick_params(axis="x", rotation=30)
    ax.legend(frameon=False, labelcolor=TEXT, fontsize=8, loc="upper right")
    return _encode(fig, "stacked_bar", f"{_prettify(cat1)} by {_prettify(cat2)} (Stacked)", "categories")


def _correlation_heatmap(df, numeric_cols):
    corr = df[numeric_cols].corr(numeric_only=True)
    fig, ax = _fig((max(5.0, 0.55 * len(numeric_cols) + 2), max(4.2, 0.55 * len(numeric_cols) + 1.5)))
    sns.heatmap(
        corr, ax=ax, cmap=sns.diverging_palette(10, 170, s=70, l=45, as_cmap=True),
        vmin=-1, vmax=1, annot=True, fmt=".2f", annot_kws={"fontsize": 8, "color": "#0a0f1c"},
        cbar_kws={"shrink": 0.85}, linewidths=0.5, linecolor=BG,
        xticklabels=[_prettify(c) for c in corr.columns], yticklabels=[_prettify(c) for c in corr.index],
    )
    ax.set_title("Correlation Matrix", color=TEXT, fontsize=11, pad=10)
    plt.setp(ax.get_xticklabels(), rotation=40, ha="right")
    return _encode(fig, "correlation_heatmap", "Correlation Matrix", "relationships")


def _pair_plot(df, cols):
    if len(cols) < 2:
        return None
    plot_df = df[cols].dropna(how="all")
    for c in cols:
        plot_df[c] = plot_df[c].fillna(plot_df[c].median())
    total = len(plot_df)
    sampled = total > 1500
    if sampled:
        plot_df = plot_df.sample(n=1500, random_state=0)
    plot_df = plot_df.rename(columns={c: _prettify(c) for c in cols})

    g = sns.PairGrid(plot_df, height=1.6, corner=True)
    g.map_diag(sns.histplot, color=PALETTE[0], bins=20)
    g.map_lower(plt.scatter, s=8, alpha=0.5, color=PALETTE[1])
    g.figure.patch.set_facecolor(BG)
    for ax in g.figure.axes:
        ax.set_facecolor(BG)
        ax.tick_params(colors=MUTED, labelsize=7)
        ax.xaxis.label.set_color(TEXT)
        ax.yaxis.label.set_color(TEXT)
        for spine in ax.spines.values():
            spine.set_color(GRID)
    g.figure.suptitle("Pair Plot (Feature Relationships)", color=TEXT, fontsize=11, y=1.02)

    buf = io.BytesIO()
    g.figure.tight_layout()
    g.figure.savefig(buf, format="png", facecolor=BG, dpi=110)
    plt.close(g.figure)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "id": "pair_plot", "title": "Pair Plot (Feature Relationships)", "category": "relationships",
        "sampled": sampled, "sample_size": len(plot_df), "total_size": total, "image_base64": b64,
    }


def _bubble_chart(df, xcol, ycol, scol):
    sub = df[[xcol, ycol, scol]].dropna()
    if sub.empty:
        return None
    total = len(sub)
    sampled = total > 2000
    if sampled:
        sub = sub.sample(n=2000, random_state=0)
    sizes = sub[scol]
    size_range = sizes.max() - sizes.min()
    scaled = (20 + 180 * (sizes - sizes.min()) / size_range) if size_range > 0 else 60

    fig, ax = _fig()
    ax.scatter(sub[xcol], sub[ycol], s=scaled, c=PALETTE[1], alpha=0.45, edgecolors="none")
    ax.set_title(f"{_prettify(xcol)} vs {_prettify(ycol)} (size = {_prettify(scol)})", color=TEXT, fontsize=11, pad=10)
    ax.set_xlabel(_prettify(xcol), color=MUTED)
    ax.set_ylabel(_prettify(ycol), color=MUTED)
    return _encode(fig, "bubble_chart", f"{_prettify(xcol)} vs {_prettify(ycol)} (bubble size = {_prettify(scol)})",
                    "relationships", sampled=sampled, sample_size=len(sub), total_size=total)


def _time_series(df, dcol, ncol):
    ts = df[[dcol, ncol]].dropna()
    if ts.empty:
        return None
    monthly = ts.set_index(dcol)[ncol].resample("MS").sum()
    rolling = monthly.rolling(window=min(3, max(1, len(monthly))), min_periods=1).mean()

    fig, ax = _fig((7.0, 4.0))
    ax.plot(monthly.index, monthly.values, marker="o", markersize=3, color=PALETTE[0], linewidth=1.6, label=_prettify(ncol))
    ax.plot(rolling.index, rolling.values, linestyle="--", color=PALETTE[2], linewidth=1.6, label="Rolling Average")
    ax.set_title(f"{_prettify(ncol)} Over Time", color=TEXT, fontsize=11, pad=10)
    ax.tick_params(axis="x", rotation=30)
    ax.legend(frameon=False, labelcolor=TEXT, fontsize=8)
    return _encode(fig, "time_series", f"{_prettify(ncol)} Over Time (with 3-period rolling average)", "time")


def _monthly_volume(df, dcol):
    counts = df[dcol].dropna().dt.to_period("M").value_counts().sort_index()
    if len(counts) <= 1:
        return None
    fig, ax = _fig((7.0, 3.6))
    ax.bar([str(p) for p in counts.index], counts.values, color=PALETTE[1])
    ax.set_title("Record Volume by Month", color=TEXT, fontsize=11, pad=10)
    ax.tick_params(axis="x", rotation=45)
    return _encode(fig, "monthly_volume", "Record Volume by Month", "time")


def _missing_matrix(sample: pd.DataFrame):
    fig, ax = _fig((6.4, 4.2))
    mask = sample.isna().astype(int)
    sns.heatmap(mask.T, ax=ax, cmap=[BG, "#e05c5c"], cbar=False, yticklabels=[_prettify(c) for c in sample.columns])
    ax.set_title("Missing Value Matrix (first 200 rows)", color=TEXT, fontsize=11, pad=10)
    ax.set_xlabel("Row", color=MUTED)
    ax.set_xticks([])
    return _encode(fig, "missing_matrix", "Missing Value Matrix (first 200 rows)", "quality")
