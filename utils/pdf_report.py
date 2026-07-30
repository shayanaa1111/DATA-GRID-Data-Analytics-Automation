"""
PDF report generation.

Uses reportlab (pure-Python, no system libraries required — unlike
WeasyPrint/wkhtmltopdf, which need Cairo/Pango/Chromium installed on the
host) so this works the same on a laptop and on a minimal PaaS deploy.
Charts are rendered to PNG with matplotlib's non-interactive Agg backend
and embedded as images.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

NAVY = colors.HexColor("#1B2540")
TEAL = colors.HexColor("#22D3B8")
MUTED = colors.HexColor("#666666")
LIGHT = colors.HexColor("#F2F4F8")

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": "#cccccc",
    "axes.labelcolor": "#333333",
    "text.color": "#222222",
    "xtick.color": "#555555",
    "ytick.color": "#555555",
    "font.size": 9,
})
CHART_COLORS = ["#22a894", "#4f8ef7", "#e8951f", "#e05c5c", "#8a6fd4"]


def generate_pdf_report(filename: str, df: pd.DataFrame, profile: dict,
                         cleaning_log: list[str], kpi_cards: list[dict],
                         ai_summary: str | None) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
    )
    styles = _styles()
    story = []

    # ---- Title ----
    story.append(Paragraph(f"{filename}", styles["ReportTitle"]))
    story.append(Paragraph("Business Analytics Report", styles["ReportSubtitle"]))
    story.append(Paragraph(
        f"Generated {datetime.now(timezone.utc).strftime('%B %d, %Y at %H:%M UTC')} by Datagrid",
        styles["Meta"],
    ))
    story.append(Spacer(1, 16))

    # ---- KPI summary table ----
    story.append(Paragraph("Key Metrics", styles["H2"]))
    kpi_rows = [["Metric", "Value"]]
    for k in kpi_cards:
        val = f"{k['value']:,.2f}" if k["format"] == "number" else f"{k['value']:,}"
        kpi_rows.append([k["label"], val])
    story.append(_styled_table(kpi_rows, col_widths=[3.5 * inch, 2.5 * inch]))
    story.append(Spacer(1, 14))

    # ---- Data quality ----
    story.append(Paragraph("Data Quality", styles["H2"]))
    quality_rows = [
        ["Rows", f"{profile['shape']['rows']:,}"],
        ["Columns", str(profile["shape"]["columns"])],
        ["Data Quality Score", f"{profile['quality_score']} / 100"],
        ["Duplicate Rows Found", str(profile["duplicate_rows"])],
        ["Missing Data", f"{profile['total_missing_pct']}% of all cells"],
    ]
    story.append(_styled_table([["Metric", "Value"]] + quality_rows, col_widths=[3.5 * inch, 2.5 * inch]))
    story.append(Spacer(1, 14))

    # ---- AI executive summary ----
    if ai_summary:
        story.append(Paragraph("AI Executive Summary", styles["H2"]))
        for block in _markdown_to_paragraphs(ai_summary, styles):
            story.append(block)
        story.append(Spacer(1, 10))

    # ---- Charts ----
    chart_images = _build_chart_images(df)
    if chart_images:
        story.append(PageBreak())
        story.append(Paragraph("Exploratory Charts", styles["H2"]))
        for title, img_bytes in chart_images:
            story.append(Paragraph(title, styles["ChartTitle"]))
            story.append(Image(io.BytesIO(img_bytes), width=6.2 * inch, height=3.0 * inch))
            story.append(Spacer(1, 10))

    # ---- Cleaning log ----
    story.append(PageBreak())
    story.append(Paragraph("Data Cleaning Log", styles["H2"]))
    if cleaning_log:
        for step in cleaning_log:
            story.append(Paragraph(f"&bull;&nbsp; {step}", styles["Body"]))
    else:
        story.append(Paragraph("No cleaning was necessary; the dataset was already tidy.", styles["Body"]))
    story.append(Spacer(1, 14))

    # ---- Column profile ----
    story.append(Paragraph("Column Profile", styles["H2"]))
    col_rows = [["Column", "Type", "Missing %", "Unique"]]
    for c in profile["columns"][:40]:
        col_rows.append([c["name"], c["dtype"], f"{c['missing_pct']}%", str(c["unique_count"])])
    story.append(_styled_table(col_rows, col_widths=[2.3 * inch, 1.3 * inch, 1.2 * inch, 1.2 * inch]))

    doc.build(story)
    return buffer.getvalue()


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("ReportTitle", parent=ss["Title"], fontSize=22, textColor=NAVY, spaceAfter=2))
    ss.add(ParagraphStyle("ReportSubtitle", parent=ss["Normal"], fontSize=12, textColor=TEAL, spaceAfter=4))
    ss.add(ParagraphStyle("Meta", parent=ss["Normal"], fontSize=9, textColor=MUTED, spaceAfter=6))
    ss.add(ParagraphStyle("H2", parent=ss["Heading2"], fontSize=14, textColor=NAVY, spaceBefore=10, spaceAfter=6))
    ss.add(ParagraphStyle("Body", parent=ss["Normal"], fontSize=9.5, leading=14, spaceAfter=3))
    ss.add(ParagraphStyle("ChartTitle", parent=ss["Normal"], fontSize=10, textColor=NAVY, spaceAfter=4, fontName="Helvetica-Bold"))
    return ss


def _styled_table(rows, col_widths):
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _markdown_to_paragraphs(md: str, styles) -> list:
    blocks = []
    for line in md.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", line)
        if line.startswith("### ") or line.startswith("## "):
            text = line.lstrip("#").strip()
            blocks.append(Paragraph(f"<b>{text}</b>", styles["Body"]))
        elif line.startswith("- "):
            blocks.append(Paragraph(f"&bull;&nbsp; {line[2:]}", styles["Body"]))
        else:
            blocks.append(Paragraph(line, styles["Body"]))
    return blocks


def _build_chart_images(df: pd.DataFrame) -> list[tuple[str, bytes]]:
    from utils.charts import _is_identifier_column  # local import avoids a hard dependency cycle

    images = []
    numeric_cols = [c for c in df.select_dtypes(include=np.number).columns if not _is_identifier_column(df, c)][:4]
    categorical_cols = [c for c in df.select_dtypes(include="object").columns
                         if 1 < df[c].nunique(dropna=True) <= 15][:2]

    for i, col in enumerate(numeric_cols):
        series = df[col].dropna()
        if series.empty:
            continue
        fig, ax = plt.subplots(figsize=(6.2, 3.0), dpi=150)
        ax.hist(series, bins=25, color=CHART_COLORS[i % len(CHART_COLORS)], edgecolor="white", linewidth=0.4)
        ax.set_title(f"Distribution of {col.replace('_', ' ').title()}", fontsize=10, color="#1B2540")
        ax.spines[["top", "right"]].set_visible(False)
        images.append((f"Distribution of {col.replace('_', ' ').title()}", _fig_to_png(fig)))

    for i, col in enumerate(categorical_cols):
        counts = df[col].value_counts(dropna=True).head(8)
        if counts.empty:
            continue
        fig, ax = plt.subplots(figsize=(6.2, 3.0), dpi=150)
        ax.barh(counts.index.astype(str)[::-1], counts.values[::-1], color=CHART_COLORS[(i + 1) % len(CHART_COLORS)])
        ax.set_title(f"Top {col.replace('_', ' ').title()} Categories", fontsize=10, color="#1B2540")
        ax.spines[["top", "right"]].set_visible(False)
        images.append((f"Top {col.replace('_', ' ').title()} Categories", _fig_to_png(fig)))

    if len(numeric_cols) >= 2:
        corr = df[numeric_cols].corr(numeric_only=True)
        fig, ax = plt.subplots(figsize=(5.2, 4.2), dpi=150)
        im = ax.imshow(corr.values, cmap="RdYlGn", vmin=-1, vmax=1)
        ax.set_xticks(range(len(corr.columns)))
        ax.set_xticklabels([c.replace("_", " ").title() for c in corr.columns], rotation=45, ha="right", fontsize=7)
        ax.set_yticks(range(len(corr.index)))
        ax.set_yticklabels([c.replace("_", " ").title() for c in corr.index], fontsize=7)
        for r in range(len(corr.index)):
            for c in range(len(corr.columns)):
                ax.text(c, r, f"{corr.values[r, c]:.2f}", ha="center", va="center", fontsize=6, color="#222")
        fig.colorbar(im, ax=ax, shrink=0.8)
        ax.set_title("Correlation Matrix", fontsize=10, color="#1B2540")
        images.append(("Correlation Matrix", _fig_to_png(fig)))

    return images


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
