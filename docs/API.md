# API Reference

All endpoints return JSON unless noted otherwise. Errors are always
`{"error": "message"}` with a non-2xx status code.

## Upload & data sources

| Method | Path | Description |
|---|---|---|
| POST | `/api/upload` | Upload a file (csv/xlsx/xls/json/tsv/txt/zip). Rate-limited: 15/min. |
| POST | `/api/upload-from-batch/<batch_id>` | Finalize a file chosen from an uploaded `.zip`. |
| POST | `/api/db/list-tables` | `{dialect, host, port, database, username, password}` → `{tables: [...]}` |
| POST | `/api/db/load-table` | `{table_name}` → imports a table as a new dataset. |
| POST | `/api/pin/<dataset_id>` | Toggle pinned state → `{pinned: bool}` |

## Data & downloads

| Method | Path | Description |
|---|---|---|
| GET | `/api/data/<id>?page=&page_size=` | Paginated data preview (page_size 10–200). |
| GET | `/api/download/<id>/raw` | Raw dataset as CSV. |
| GET | `/api/download/<id>/clean` | Cleaned dataset as CSV. |

## SQL Analytics

| Method | Path | Description |
|---|---|---|
| GET | `/api/sql/<id>/schema` | Column names + SQLite types. |
| POST | `/api/sql/<id>/execute` | `{sql}` → read-only query (SELECT/WITH/EXPLAIN only). |
| POST | `/api/sql/<id>/nl2sql` | `{question}` → AI-generated SQL + results. Rate-limited: 15/min. |
| POST | `/api/sql/<id>/explain` | `{sql}` → plain-English explanation. Rate-limited: 20/min. |
| POST | `/api/sql/<id>/optimize` | `{sql}` → AI-suggested rewrite. Rate-limited: 15/min. |
| GET | `/api/sql/<id>/history` | Last 50 executed queries. |
| DELETE | `/api/sql/<id>/history` | Clear history. |
| GET | `/api/sql/<id>/saved` | List saved/favorite queries. |
| POST | `/api/sql/<id>/saved` | `{name, sql}` → save a query. |
| DELETE | `/api/sql/<id>/saved/<query_id>` | Delete a saved query. |

## AI Chat

| Method | Path | Description |
|---|---|---|
| GET | `/api/chat/<id>/sessions` | List chat sessions for this dataset. |
| POST | `/api/chat/<id>/sessions` | Create a new chat session. |
| GET | `/api/chat/<id>/sessions/<chat_id>` | Get a session's full message history. |
| PATCH | `/api/chat/<id>/sessions/<chat_id>` | `{title}` → rename. |
| DELETE | `/api/chat/<id>/sessions/<chat_id>` | Delete a session. |
| POST | `/api/chat/<id>` | `{question, chat_id, history}` → answer + `followups[]`. Rate-limited: 30/min. |
| POST | `/api/insights/<id>` | Generate (and cache) the AI executive summary. Rate-limited: 10/min. |
| POST | `/api/explain-chart/<id>` | `{chart_title}` → AI explanation of a chart. Rate-limited: 30/min. |

## Exports & reports

| Method | Path | Description |
|---|---|---|
| GET | `/api/export/excel/<id>` | Full Excel workbook (8 sheets). `?ai=0` skips the AI Search sheet. |
| GET | `/api/report/<id>/markdown` | Markdown report. |
| GET | `/api/report/<id>/html` | Standalone HTML report (`?download=1` to force download). |
| GET | `/api/report/<id>/pdf` | PDF report. |
| GET | `/api/report/<id>/json` | Structured JSON export (profile, KPIs, insights, cleaning log). |

## Admin

| Method | Path | Description |
|---|---|---|
| GET | `/admin/activity?token=<ADMIN_TOKEN>` | Recent activity log (uploads, queries, AI requests). Disabled unless `ADMIN_TOKEN` is set. |

## Notes

- All dataset-scoped endpoints 404 with `{"error": "Dataset not found."}` if `dataset_id` doesn't exist.
- All AI-backed endpoints return 503 with a clear message if `GROQ_API_KEY` isn't set, and 502 if the Groq API call itself fails.
- Rate-limited endpoints return 429 with `{"error": "Rate limit exceeded. Try again in Xs."}`.
