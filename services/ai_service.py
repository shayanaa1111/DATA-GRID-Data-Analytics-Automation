"""
Thin wrapper around the Groq API.

Groq's API is OpenAI-compatible: POST {GROQ_API_BASE}/chat/completions with
a Bearer token. We call it with plain `requests` so the app has no extra
SDK dependency. The API key is read only from the environment (GROQ_API_KEY)
via config.py — it is never hardcoded and never sent to the browser.

All prompt text lives in services/prompts.py, not here — this module is
purely the transport + a small set of typed helper functions.
"""
from __future__ import annotations

import json
import logging
import re
import time

import requests

from config import Config
from services import prompts

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class AIServiceError(Exception):
    pass


def _call_groq(messages: list[dict], temperature: float = 0.4, max_tokens: int = 900) -> str:
    if not Config.AI_ENABLED:
        raise AIServiceError(
            "No GROQ_API_KEY is set. Add it to your .env file (see .env.example) "
            "to enable AI features."
        )

    url = f"{Config.GROQ_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": Config.GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
                wait = 0.5 * (2 ** attempt)
                logger.warning("Groq API returned %s, retrying in %.1fs (attempt %d/%d)",
                                resp.status_code, wait, attempt + 1, MAX_RETRIES)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except requests.exceptions.HTTPError as exc:
            body = exc.response.text[:500] if exc.response is not None else str(exc)
            logger.error("Groq API HTTP error: %s", body)
            last_error = AIServiceError(f"Groq API returned an error: {body}")
            break
        except (requests.exceptions.RequestException, KeyError, json.JSONDecodeError) as exc:
            last_error = AIServiceError(f"Could not reach the Groq API: {exc}")
            if attempt < MAX_RETRIES:
                wait = 0.5 * (2 ** attempt)
                logger.warning("Groq API call failed (%s), retrying in %.1fs", exc, wait)
                time.sleep(wait)
                continue
            logger.error("Groq API call failed after retries: %s", exc)
            break

    raise last_error


def build_dataset_context(profile: dict, sample_rows: list[dict], filename: str) -> str:
    """Compact, token-efficient description of the dataset for the AI to reason over."""
    cols_desc = "\n".join(
        f"- {c['name']} ({c['dtype']}): {c['missing_pct']}% missing, "
        f"{c['unique_count']} unique values"
        for c in profile["columns"]
    )
    numeric_desc = "\n".join(
        f"- {col}: mean={stats.get('mean')}, median={stats.get('median')}, "
        f"min={stats.get('min')}, max={stats.get('max')}"
        for col, stats in profile.get("numeric_summary", {}).items()
    )
    cat_desc = "\n".join(
        f"- {col}: top values = "
        + ", ".join(f"{tv['value']} ({tv['count']})" for tv in stats.get("top_values", [])[:5])
        for col, stats in profile.get("categorical_summary", {}).items()
    )

    return f"""Dataset file: {filename}
Shape: {profile['shape']['rows']} rows x {profile['shape']['columns']} columns
Data quality score: {profile.get('quality_score')}/100
Duplicate rows removed during cleaning: {profile.get('duplicate_rows')}

COLUMNS:
{cols_desc}

NUMERIC COLUMN STATISTICS:
{numeric_desc or 'None'}

CATEGORICAL COLUMN TOP VALUES:
{cat_desc or 'None'}

SAMPLE ROWS (first {len(sample_rows)}):
{json.dumps(sample_rows, default=str, indent=None)}
"""


def chat_with_dataset(question: str, dataset_context: str, history: list[dict] | None = None) -> str:
    messages = [{"role": "system", "content": prompts.CHAT_SYSTEM_PROMPT + "\n\nDATASET CONTEXT:\n" + dataset_context}]
    for turn in (history or [])[-6:]:  # keep last few turns only, stay cheap
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})
    return _call_groq(messages)


def suggest_followups(dataset_context: str, history: list[dict]) -> list[str]:
    """Returns up to 3 suggested follow-up questions given the conversation so
    far. Best-effort: returns an empty list rather than raising, since this
    is a nice-to-have UI affordance, not a core answer."""
    messages = [{"role": "system", "content": prompts.CHAT_SYSTEM_PROMPT + "\n\nDATASET CONTEXT:\n" + dataset_context}]
    for turn in (history or [])[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": prompts.FOLLOWUP_SUGGESTION_PROMPT})
    try:
        raw = _call_groq(messages, temperature=0.6, max_tokens=200)
        raw = re.sub(r"^```(json)?", "", raw.strip(), flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(q) for q in parsed][:3]
    except (AIServiceError, json.JSONDecodeError, ValueError):
        pass
    return []


def generate_executive_summary(dataset_context: str) -> str:
    messages = [
        {"role": "system", "content": prompts.CHAT_SYSTEM_PROMPT + "\n\nDATASET CONTEXT:\n" + dataset_context},
        {"role": "user", "content": prompts.executive_summary_prompt()},
    ]
    return _call_groq(messages, temperature=0.5, max_tokens=1100)


def explain_chart(chart_title: str, dataset_context: str) -> str:
    messages = [
        {"role": "system", "content": prompts.CHAT_SYSTEM_PROMPT + "\n\nDATASET CONTEXT:\n" + dataset_context},
        {"role": "user", "content": prompts.chart_explanation_prompt(chart_title)},
    ]
    return _call_groq(messages, temperature=0.4, max_tokens=220)


def natural_language_to_sql(question: str, schema: list[dict]) -> str:
    schema_desc = "\n".join(f"- {c['name']} ({c['type']})" for c in schema)
    messages = [
        {"role": "system", "content": prompts.SQL_GENERATION_SYSTEM_PROMPT},
        {"role": "user", "content": prompts.sql_generation_user_prompt(question, schema_desc)},
    ]
    raw = _call_groq(messages, temperature=0.1, max_tokens=400)
    return _strip_code_fences(raw)


def explain_sql(sql: str) -> str:
    messages = [
        {"role": "system", "content": prompts.SQL_EXPLAIN_SYSTEM_PROMPT},
        {"role": "user", "content": sql},
    ]
    return _call_groq(messages, temperature=0.3, max_tokens=250)


def optimize_sql(sql: str, schema: list[dict]) -> str:
    schema_desc = "\n".join(f"- {c['name']} ({c['type']})" for c in schema)
    messages = [
        {"role": "system", "content": prompts.SQL_OPTIMIZE_SYSTEM_PROMPT},
        {"role": "user", "content": prompts.sql_optimize_user_prompt(sql, schema_desc)},
    ]
    raw = _call_groq(messages, temperature=0.1, max_tokens=400)
    return _strip_code_fences(raw)


def _strip_code_fences(raw: str) -> str:
    raw = re.sub(r"^```(sql)?", "", raw.strip(), flags=re.IGNORECASE).strip()
    raw = re.sub(r"```$", "", raw).strip()
    return raw
