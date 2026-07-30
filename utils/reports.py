"""
Generates portable business reports from a dataset's profile/KPIs/charts:
  - Markdown (plain text, pastes cleanly into Notion/Slack/docs)
  - Standalone HTML (self-contained, opens in any browser, charts included)

PDF generation lives in pdf_report.py (needs a different toolkit: reportlab).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd


def generate_markdown_report(filename: str, profile: dict, cleaning_log: list[str],
                              kpi_cards: list[dict], ai_summary: str | None) -> str:
    lines = [
        f"# {filename} — Business Report",
        f"*Generated {_now()} by Datagrid*",
        "",
        "## Overview",
        f"- **Rows:** {profile['shape']['rows']:,}",
        f"- **Columns:** {profile['shape']['columns']}",
        f"- **Data quality score:** {profile['quality_score']}/100",
        f"- **Duplicate rows found before cleaning:** {profile['duplicate_rows']}",
        f"- **Missing data:** {profile['total_missing_pct']}% of all cells",
        "",
        "## Key Metrics",
    ]
    for kpi in kpi_cards:
        val = f"{kpi['value']:,.2f}" if kpi["format"] == "number" else f"{kpi['value']:,}"
        lines.append(f"- **{kpi['label']}:** {val}")
    lines.append("")

    if ai_summary:
        lines += ["## AI Executive Summary", "", ai_summary, ""]

    lines += ["## Data Cleaning Log", ""]
    if cleaning_log:
        lines += [f"- {step}" for step in cleaning_log]
    else:
        lines.append("- No cleaning was necessary; the dataset was already tidy.")
    lines.append("")

    if profile.get("numeric_summary"):
        lines += ["## Numeric Column Summary", "", "| Column | Mean | Median | Std | Min | Max |", "|---|---|---|---|---|---|"]
        for col, s in profile["numeric_summary"].items():
            lines.append(f"| {col} | {s['mean']} | {s['median']} | {s['std']} | {s['min']} | {s['max']} |")
        lines.append("")

    if profile.get("categorical_summary"):
        lines += ["## Categorical Column Summary", ""]
        for col, s in profile["categorical_summary"].items():
            top = ", ".join(f"{tv['value']} ({tv['count']})" for tv in s["top_values"][:5])
            lines.append(f"- **{col}** ({s['unique_count']} unique values): {top}")
        lines.append("")

    lines += ["## Column Profile", "", "| Column | Type | Missing % | Unique |", "|---|---|---|---|"]
    for c in profile["columns"]:
        lines.append(f"| {c['name']} | {c['dtype']} | {c['missing_pct']}% | {c['unique_count']} |")

    return "\n".join(lines)


def generate_html_report(filename: str, profile: dict, cleaning_log: list[str],
                          kpi_cards: list[dict], charts: list[dict], ai_summary: str | None) -> str:
    """`charts` here are image-chart dicts from utils/chart_images.py
    ({id, title, image_base64, ...}), not a JS charting library's config —
    this report is a single self-contained HTML file with zero external
    requests, so it still renders correctly opened completely offline."""
    kpi_blocks = []
    for k in kpi_cards:
        val = f"{k['value']:,.2f}" if k["format"] == "number" else f"{k['value']:,}"
        kpi_blocks.append(
            f'<div class="kpi"><div class="kpi-label">{_esc(k["label"])}</div>'
            f'<div class="kpi-value">{val}</div></div>'
        )
    kpi_html = "\n".join(kpi_blocks)

    col_rows = "\n".join(
        f"<tr><td>{_esc(c['name'])}</td><td>{_esc(c['dtype'])}</td>"
        f"<td>{c['missing_pct']}%</td><td>{c['unique_count']}</td></tr>"
        for c in profile["columns"]
    )

    log_items = "\n".join(f"<li>{_esc(step)}</li>" for step in cleaning_log) or "<li>No cleaning was necessary.</li>"

    ai_section = ""
    if ai_summary:
        ai_html = _markdown_to_html_basic(ai_summary)
        ai_section = f'<section><h2>AI Executive Summary</h2>{ai_html}</section>'

    chart_divs = []
    for chart in charts:
        sample_note = (
            f'<div class="sample-note">Showing {chart["sample_size"]:,} of {chart["total_size"]:,} points (sampled for performance)</div>'
            if chart.get("sampled") else ""
        )
        chart_divs.append(
            f'<div class="chart-card"><div class="chart-card-title">{_esc(chart["title"])}</div>{sample_note}'
            f'<img src="data:image/png;base64,{chart["image_base64"]}" alt="{_esc(chart["title"])}"></div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{_esc(filename)} — Business Report</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background:#0a0f1c; color:#e7ecf5; margin:0; padding:40px; }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  h1 {{ font-size: 26px; margin-bottom:4px; }}
  .meta {{ color:#8b98b3; font-size:13px; margin-bottom:30px; }}
  h2 {{ font-size:18px; border-bottom:1px solid #223050; padding-bottom:8px; margin-top:40px; }}
  .kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; }}
  .kpi {{ background:#111a2c; border:1px solid #223050; border-radius:10px; padding:16px; }}
  .kpi-label {{ font-size:12px; color:#8b98b3; margin-bottom:6px; }}
  .kpi-value {{ font-family: monospace; font-size:22px; font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:10px; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #223050; }}
  th {{ background:#17223a; color:#8b98b3; }}
  .chart-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:16px; margin-top:16px;}}
  .chart-card {{ background:#111a2c; border:1px solid #223050; border-radius:10px; padding:10px; }}
  .chart-card-title {{ font-size:13px; font-weight:600; margin-bottom:8px; padding:0 4px; }}
  .chart-card img {{ width:100%; height:auto; border-radius:6px; display:block; }}
  .sample-note {{ font-size:11px; color:#8b98b3; padding:0 4px 6px; }}
  ul {{ padding-left: 18px; }}
  li {{ margin-bottom: 6px; color:#c3cbdb; }}
  @media print {{ body {{ background:#fff; color:#111; }} .kpi, .chart-card {{ border-color:#ccc; }} }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{_esc(filename)} — Business Report</h1>
  <div class="meta">Generated {_now()} by Datagrid &middot; {profile['shape']['rows']:,} rows &middot; {profile['shape']['columns']} columns &middot; Quality score {profile['quality_score']}/100</div>

  <section>
    <h2>Key Metrics</h2>
    <div class="kpi-grid">{kpi_html}</div>
  </section>

  {ai_section}

  <section>
    <h2>Exploratory Charts</h2>
    <div class="chart-grid">{''.join(chart_divs)}</div>
  </section>

  <section>
    <h2>Data Cleaning Log</h2>
    <ul>{log_items}</ul>
  </section>

  <section>
    <h2>Column Profile</h2>
    <table>
      <thead><tr><th>Column</th><th>Type</th><th>Missing %</th><th>Unique</th></tr></thead>
      <tbody>{col_rows}</tbody>
    </table>
  </section>
</div>
</body>
</html>"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")


def _esc(text) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _markdown_to_html_basic(md: str) -> str:
    import re
    text = _esc(md)
    text = re.sub(r"^### (.*)$", r"<h4>\1</h4>", text, flags=re.M)
    text = re.sub(r"^## (.*)$", r"<h3>\1</h3>", text, flags=re.M)
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(^|\n)- (.*)", r"\1<li>\2</li>", text)
    text = re.sub(r"(<li>.*</li>)", r"<ul>\1</ul>", text, flags=re.S)
    text = re.sub(r"\n{2,}", "</p><p>", text)
    return f"<p>{text}</p>"
