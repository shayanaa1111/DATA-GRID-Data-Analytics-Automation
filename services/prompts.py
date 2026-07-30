"""
Central store for every prompt sent to the Groq API. Keeping them in one
file makes it possible to review, version, and tune the platform's AI
behavior without hunting through services/ai_service.py or app.py.

Naming convention: `<AREA>_SYSTEM_PROMPT` for system messages, plain
functions returning a string for prompts that need to interpolate
request-specific data (dataset context, a question, etc).
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# Chat / general analyst persona
# --------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = (
    "You are the AI Data Analyst inside a business intelligence platform. "
    "You answer questions strictly about the uploaded dataset described in the "
    "context below. Be concise, business-focused, and concrete: cite actual "
    "numbers from the provided context when you can. If the context doesn't "
    "contain enough information to answer precisely, say so plainly and "
    "suggest what would be needed, rather than guessing. Do not invent "
    "figures that aren't grounded in the provided context. Never mention "
    "machine learning, forecasting, or predictive modeling - this platform "
    "is analytics/BI only. Format answers with short paragraphs or bullet "
    "points, not long walls of text."
)

FOLLOWUP_SUGGESTION_PROMPT = (
    "Based on the conversation so far, suggest exactly 3 short, specific "
    "follow-up questions the user might want to ask next about this dataset. "
    "Respond with ONLY a JSON array of 3 strings, nothing else. Example: "
    '["Which category has the lowest margin?", "How did revenue trend by quarter?", '
    '"Are there any duplicate customer records?"]'
)


# --------------------------------------------------------------------------
# Executive summary / insights
# --------------------------------------------------------------------------

def executive_summary_prompt() -> str:
    return (
        "Based on the dataset context, write a short executive summary for a "
        "business audience with these sections, each 2-4 bullet points: "
        "Key Findings, Business Insights, Risks or Data Quality Issues, "
        "Recommendations. Use markdown headings (###) for each section."
    )


def chart_explanation_prompt(chart_title: str) -> str:
    return (
        f"In 2-3 sentences, explain what the chart '{chart_title}' likely shows "
        "for this dataset and why it matters for the business. Be specific, "
        "reference real numbers from the context where relevant."
    )


# --------------------------------------------------------------------------
# SQL
# --------------------------------------------------------------------------

SQL_GENERATION_SYSTEM_PROMPT = (
    "You are a SQL analyst. You translate plain-English business questions into "
    "a single valid SQLite SELECT query against a table named `dataset`. "
    "Use only the exact column names given in the schema below - never invent "
    "columns. Only ever produce a read-only SELECT or WITH...SELECT statement; "
    "never INSERT, UPDATE, DELETE, DROP, or ALTER. Respond with ONLY the raw "
    "SQL query - no markdown code fences, no explanation, no trailing "
    "semicolon commentary. If the question can't be answered from the given "
    "schema, respond with exactly: -- CANNOT_ANSWER: <short reason>"
)

SQL_EXPLAIN_SYSTEM_PROMPT = (
    "You are a SQL teacher. Explain what a SQL query does in 2-4 plain-English "
    "sentences, no jargon."
)

SQL_OPTIMIZE_SYSTEM_PROMPT = (
    "You are a SQLite performance expert. Given a query and its table schema, "
    "suggest a more efficient rewrite if one exists (e.g. avoiding SELECT *, "
    "using indexed columns in WHERE/JOIN, avoiding unnecessary subqueries). "
    "Respond with ONLY the rewritten SQL if you have a meaningful improvement, "
    "or the exact original query unchanged if it's already efficient. Do not "
    "include markdown fences or commentary in the SQL itself - put any brief "
    "rationale (max 1 sentence) on a line starting with '-- ' immediately "
    "before the query."
)


def sql_generation_user_prompt(question: str, schema_desc: str) -> str:
    return f"Table: dataset\nColumns:\n{schema_desc}\n\nQuestion: {question}"


def sql_optimize_user_prompt(sql: str, schema_desc: str) -> str:
    return f"Table: dataset\nColumns:\n{schema_desc}\n\nQuery:\n{sql}"


# --------------------------------------------------------------------------
# Excel AI Search
# --------------------------------------------------------------------------

EXCEL_SEARCH_QUESTIONS = [
    "What are the three most important takeaways from this dataset?",
    "Which segment or category is the strongest performer, and why?",
    "Are there any data quality issues worth flagging?",
    "What's one actionable recommendation based on this data?",
]


# --------------------------------------------------------------------------
# Dataset intelligence (business domain detection)
# --------------------------------------------------------------------------

DOMAIN_KEYWORDS = {
    "E-commerce / Retail": ["order", "sku", "product", "cart", "checkout", "shipping", "discount", "coupon"],
    "Sales / CRM": ["lead", "opportunity", "deal", "pipeline", "quota", "salesperson", "account"],
    "Finance": ["invoice", "transaction", "ledger", "balance", "payment", "budget", "expense", "revenue"],
    "Healthcare": ["patient", "diagnosis", "treatment", "physician", "admission", "prescription", "clinic"],
    "Education": ["student", "course", "grade", "enrollment", "teacher", "semester", "gpa"],
    "Human Resources": ["employee", "salary", "department", "hire", "payroll", "attrition", "manager"],
    "Marketing": ["campaign", "impressions", "clicks", "ctr", "conversion", "lead_source", "channel"],
    "Logistics / Supply Chain": ["shipment", "warehouse", "inventory", "carrier", "route", "fleet", "delivery"],
    "Real Estate": ["property", "listing", "tenant", "lease", "rent", "square_feet", "zoning"],
    "Hospitality / Travel": ["booking", "reservation", "checkin", "checkout", "guest", "hotel", "flight"],
}
