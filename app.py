"""
Datagrid - AI Data Analytics Platform
Upload -> Clean -> Profile -> Dashboard -> SQL Analytics -> Excel/Reports -> AI Chat

Run locally:
    cp .env.example .env   # fill in GROQ_API_KEY
    pip install -r requirements.txt
    python app.py

Run in production (behind gunicorn, e.g. on Render/Railway/Fly/a VPS):
    gunicorn app:app --bind 0.0.0.0:$PORT --workers 3 --timeout 120
"""
from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file, session
from werkzeug.utils import secure_filename

from config import Config
from services import ai_service, prompts
from utils import activity_log, cache, chat_store, dataset_intelligence, query_store
from utils import charts as chart_utils
from utils import chart_images
from utils import business_insights as business_insights_utils
from utils import data_cleaning, data_profiling, db_connector, excel_export
from utils import multi_file, pdf_report, reports, sql_engine, storage
from utils.data_loader import UnsupportedFileError, allowed_file, load_dataset
from utils.rate_limit import rate_limit

Config.ensure_dirs()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(Config.LOG_DIR / "app.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)


# --------------------------------------------------------------------------
# Shared pipeline: raw DataFrame -> cleaned, profiled, SQL-ready, stored
# --------------------------------------------------------------------------

def _finalize_dataset(raw_df, filename: str, detected_format: str, source: str = "upload") -> str:
    if raw_df.empty:
        raise UnsupportedFileError("The file was read but contains no rows.")

    dataset_id = uuid.uuid4().hex[:12]
    clean_df, cleaning_log = data_cleaning.clean_dataset(raw_df)
    profile = data_profiling.profile_dataset(clean_df)

    storage.save_dataset(
        dataset_id=dataset_id,
        raw_df=raw_df,
        clean_df=clean_df,
        cleaning_log=cleaning_log,
        profile=profile,
        meta={
            "filename": filename,
            "detected_format": detected_format,
            "source": source,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    try:
        sql_engine.build_sqlite_db(dataset_id, clean_df)
    except Exception:  # noqa: BLE001
        logger.exception("Could not build SQL database for %s (SQL Analytics tab will be unavailable)", dataset_id)

    return dataset_id


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@app.route("/")
def home():
    recent = storage.list_recent_datasets(limit=6)
    pinned = storage.list_pinned_datasets()
    return render_template("index.html", recent=recent, pinned=pinned, ai_enabled=Config.AI_ENABLED)


@app.route("/upload")
def upload_page():
    return render_template("upload.html", max_mb=Config.MAX_UPLOAD_MB)


@app.route("/connect-database")
def connect_database_page():
    return render_template("connect_database.html", dialects=list(db_connector.DIALECT_DRIVERS.keys()))


@app.route("/choose-dataset/<batch_id>")
def choose_dataset_page(batch_id):
    files = session.get(f"batch_files_{batch_id}")
    if not files:
        return render_template(
            "upload.html", max_mb=Config.MAX_UPLOAD_MB,
            error="That archive session expired. Please upload the .zip again.",
        ), 404
    return render_template("choose_dataset.html", batch_id=batch_id, files=files)


@app.route("/dashboard/<dataset_id>")
def dashboard(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return render_template("upload.html", max_mb=Config.MAX_UPLOAD_MB,
                                error="That dataset wasn't found. Please upload again."), 404

    meta = storage.load_meta(dataset_id)
    profile = meta["profile"]
    df = storage.load_clean_df(dataset_id)

    # These are all pure functions of the (immutable, post-upload) cleaned
    # DataFrame, so they're safe to cache indefinitely per dataset_id —
    # repeat visits to a dashboard skip recomputation entirely.
    kpi_cards = cache.get_or_compute(f"kpi:{dataset_id}", lambda: chart_utils.build_kpi_cards(df))
    dashboard_charts = cache.get_or_compute(f"chart_images:{dataset_id}", lambda: chart_images.build_dashboard_chart_images(df))
    any_chart_sampled = any(c.get("sampled") for c in dashboard_charts)
    business_insights = cache.get_or_compute(f"insights:{dataset_id}", lambda: business_insights_utils.build_business_insights(df))
    intelligence = cache.get_or_compute(f"intel:{dataset_id}", lambda: dataset_intelligence.analyze_dataset(df))
    sql_ready = sql_engine.db_path(dataset_id).exists()

    session["dataset_id"] = dataset_id

    return render_template(
        "dashboard.html",
        dataset_id=dataset_id,
        filename=meta.get("filename"),
        profile=profile,
        cleaning_log=meta.get("cleaning_log", []),
        kpi_cards=kpi_cards,
        charts=dashboard_charts,
        any_chart_sampled=any_chart_sampled,
        business_insights=business_insights,
        dataset_intelligence=intelligence,
        ai_enabled=Config.AI_ENABLED,
        sql_ready=sql_ready,
        cached_summary=meta.get("ai_executive_summary"),
        pinned=meta.get("pinned", False),
        preview_columns=list(df.columns),
        preview_rows=df.head(25).fillna("").astype(str).values.tolist(),
        total_rows=len(df),
    )


# --------------------------------------------------------------------------
# API: Upload (single file, zip archive, or a file chosen from an archive)
# --------------------------------------------------------------------------

@app.route("/api/upload", methods=["POST"])
@rate_limit(max_calls=15, window_seconds=60)
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file was sent."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    safe_name = secure_filename(file.filename) or "upload"
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""

    if ext in Config.ARCHIVE_EXTENSIONS:
        return _handle_zip_upload(file)

    if not allowed_file(safe_name, Config.ALLOWED_EXTENSIONS):
        allowed = ", ".join(sorted(Config.ALLOWED_EXTENSIONS | Config.ARCHIVE_EXTENSIONS))
        return jsonify({"error": f"Unsupported file type. Allowed: {allowed}"}), 400

    dataset_id = uuid.uuid4().hex[:12]
    upload_path = Config.UPLOAD_DIR / f"{dataset_id}_{safe_name}"
    file.save(upload_path)

    try:
        with activity_log.timed_event("upload", filename=safe_name):
            raw_df, detected_format = load_dataset(upload_path)
            dataset_id = _finalize_dataset(raw_df, safe_name, detected_format)
        return jsonify({"dataset_id": dataset_id, "redirect": f"/dashboard/{dataset_id}"})
    except UnsupportedFileError as exc:
        logger.warning("Upload rejected: %s", exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected upload failure")
        return jsonify({"error": f"Something went wrong processing this file: {exc}"}), 500
    finally:
        try:
            upload_path.unlink(missing_ok=True)
        except OSError:
            pass


def _handle_zip_upload(file):
    tmp_path = Config.UPLOAD_DIR / f"_incoming_{uuid.uuid4().hex[:8]}.zip"
    file.save(tmp_path)
    try:
        batch_id, files = multi_file.extract_zip_archive(tmp_path)
        session[f"batch_files_{batch_id}"] = files
        return jsonify({"batch_id": batch_id, "redirect": f"/choose-dataset/{batch_id}", "files": files})
    except multi_file.ZipExtractionError as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        tmp_path.unlink(missing_ok=True)


@app.route("/api/upload-from-batch/<batch_id>", methods=["POST"])
def api_upload_from_batch(batch_id):
    body = request.get_json(silent=True) or {}
    relative_path = body.get("relative_path")
    if not relative_path:
        return jsonify({"error": "No file selected from the archive."}), 400

    try:
        file_path = multi_file.resolve_batch_file(batch_id, relative_path)
        raw_df, detected_format = load_dataset(file_path)
        dataset_id = _finalize_dataset(raw_df, file_path.name, detected_format, source="zip_archive")
        return jsonify({"dataset_id": dataset_id, "redirect": f"/dashboard/{dataset_id}"})
    except (multi_file.ZipExtractionError, UnsupportedFileError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected batch upload failure")
        return jsonify({"error": f"Something went wrong processing this file: {exc}"}), 500


# --------------------------------------------------------------------------
# API: Database sources
# --------------------------------------------------------------------------

@app.route("/api/db/list-tables", methods=["POST"])
def api_db_list_tables():
    body = request.get_json(silent=True) or {}
    try:
        url = db_connector.build_connection_url(
            dialect=body.get("dialect", ""), host=body.get("host", ""), port=body.get("port", ""),
            database=body.get("database", ""), username=body.get("username", ""), password=body.get("password", ""),
        )
        tables = db_connector.list_tables(url)
        session["db_connection_url"] = url  # kept server-side only, in the signed session cookie's backing store
        return jsonify({"tables": tables})
    except db_connector.DatabaseConnectionError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/db/load-table", methods=["POST"])
def api_db_load_table():
    body = request.get_json(silent=True) or {}
    table_name = body.get("table_name")
    url = session.get("db_connection_url")
    if not url:
        return jsonify({"error": "Your database connection expired. Please reconnect."}), 400
    if not table_name:
        return jsonify({"error": "No table selected."}), 400

    try:
        df = db_connector.load_table(url, table_name)
        dataset_id = _finalize_dataset(df, f"{table_name} (database)", "database", source="database")
        return jsonify({"dataset_id": dataset_id, "redirect": f"/dashboard/{dataset_id}"})
    except db_connector.DatabaseConnectionError as exc:
        return jsonify({"error": str(exc)}), 400
    except UnsupportedFileError as exc:
        return jsonify({"error": str(exc)}), 400


# --------------------------------------------------------------------------
# API: Downloads (CSV)
# --------------------------------------------------------------------------

@app.route("/api/pin/<dataset_id>", methods=["POST"])
def api_toggle_pin(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    pinned = storage.toggle_pin(dataset_id)
    return jsonify({"pinned": pinned})


@app.route("/api/data/<dataset_id>")
def api_data_page(dataset_id):
    """Paginated data preview — the dashboard's initial render ships only
    the first 25 rows; this endpoint powers 'load more' / page navigation
    in the Data Preview tab without re-sending the whole dataset."""
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404

    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(200, max(10, int(request.args.get("page_size", 25))))
    except ValueError:
        return jsonify({"error": "Invalid pagination parameters."}), 400

    df = cache.get_or_compute(f"df:{dataset_id}", lambda: storage.load_clean_df(dataset_id))
    total_rows = len(df)
    start = (page - 1) * page_size
    page_df = df.iloc[start:start + page_size]

    return jsonify({
        "columns": list(df.columns),
        "rows": page_df.fillna("").astype(str).values.tolist(),
        "page": page,
        "page_size": page_size,
        "total_rows": total_rows,
        "total_pages": max(1, -(-total_rows // page_size)),
    })


@app.route("/api/download/<dataset_id>/<kind>")
def api_download(dataset_id, kind):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404

    df = storage.load_raw_df(dataset_id) if kind == "raw" else storage.load_clean_df(dataset_id)
    csv_data = df.to_csv(index=False)
    filename = f"{kind}_{dataset_id}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# --------------------------------------------------------------------------
# API: SQL Analytics
# --------------------------------------------------------------------------

@app.route("/api/sql/<dataset_id>/schema")
def api_sql_schema(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    try:
        return jsonify({"table": sql_engine.TABLE_NAME, "columns": sql_engine.table_schema(dataset_id)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.route("/api/sql/<dataset_id>/execute", methods=["POST"])
def api_sql_execute(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    body = request.get_json(silent=True) or {}
    sql = body.get("sql", "")
    try:
        with activity_log.timed_event("sql_query", dataset_id=dataset_id):
            result = sql_engine.run_query(dataset_id, sql)
        query_store.log_query(dataset_id, sql, result["row_count"], source="manual")
        return jsonify(result)
    except sql_engine.UnsafeQueryError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/sql/<dataset_id>/chart", methods=["POST"])
def api_sql_chart(dataset_id):
    """Renders a server-side PNG for the 'Chart Results' button in the SQL
    editor, given the columns/rows already returned by /execute or
    /nl2sql. Server-rendered (matplotlib) rather than client-side Plotly,
    for the same reliability reasons as the main dashboard charts — no
    external script, can't be blocked by a network/ad-blocker."""
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    body = request.get_json(silent=True) or {}
    columns = body.get("columns") or []
    rows = body.get("rows") or []
    image_b64 = chart_images.render_query_chart(columns, rows)
    if image_b64 is None:
        return jsonify({"error": "This result doesn't have a numeric column to chart."}), 400
    return jsonify({"image_base64": image_b64})


@app.route("/api/sql/<dataset_id>/history")
def api_sql_history(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    return jsonify({"history": query_store.get_history(dataset_id)})


@app.route("/api/sql/<dataset_id>/history", methods=["DELETE"])
def api_sql_history_clear(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    query_store.clear_history(dataset_id)
    return jsonify({"cleared": True})


@app.route("/api/sql/<dataset_id>/saved", methods=["GET"])
def api_sql_saved_list(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    return jsonify({"saved": query_store.get_saved_queries(dataset_id)})


@app.route("/api/sql/<dataset_id>/saved", methods=["POST"])
def api_sql_saved_create(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    sql = (body.get("sql") or "").strip()
    if not name or not sql:
        return jsonify({"error": "Both a name and a query are required."}), 400
    entry = query_store.save_query(dataset_id, name, sql)
    return jsonify(entry)


@app.route("/api/sql/<dataset_id>/saved/<query_id>", methods=["DELETE"])
def api_sql_saved_delete(dataset_id, query_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    deleted = query_store.delete_saved_query(dataset_id, query_id)
    return jsonify({"deleted": deleted})


@app.route("/api/sql/<dataset_id>/nl2sql", methods=["POST"])
@rate_limit(max_calls=15, window_seconds=60)
def api_sql_nl2sql(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    if not Config.AI_ENABLED:
        return jsonify({"error": "AI features are disabled. Set GROQ_API_KEY in your .env file."}), 503

    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()[:500]
    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    sql = None
    try:
        with activity_log.timed_event("ai_request", dataset_id=dataset_id, kind="nl2sql"):
            schema = sql_engine.table_schema(dataset_id)
            sql = ai_service.natural_language_to_sql(question, schema)
            if sql.strip().upper().startswith("-- CANNOT_ANSWER"):
                return jsonify({"error": sql.strip()}), 422
            result = sql_engine.run_query(dataset_id, sql)
        result["sql"] = sql
        query_store.log_query(dataset_id, sql, result["row_count"], source="nl2sql")
        return jsonify(result)
    except ai_service.AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502
    except sql_engine.UnsafeQueryError as exc:
        return jsonify({"error": f"The AI generated an invalid query: {exc}", "sql": sql}), 400


@app.route("/api/sql/<dataset_id>/explain", methods=["POST"])
@rate_limit(max_calls=20, window_seconds=60)
def api_sql_explain(dataset_id):
    if not Config.AI_ENABLED:
        return jsonify({"error": "AI features are disabled. Set GROQ_API_KEY in your .env file."}), 503
    body = request.get_json(silent=True) or {}
    sql = (body.get("sql") or "").strip()[:5000]
    if not sql:
        return jsonify({"error": "No SQL to explain."}), 400
    try:
        with activity_log.timed_event("ai_request", dataset_id=dataset_id, kind="sql_explain"):
            explanation = ai_service.explain_sql(sql)
        return jsonify({"explanation": explanation})
    except ai_service.AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/sql/<dataset_id>/optimize", methods=["POST"])
@rate_limit(max_calls=15, window_seconds=60)
def api_sql_optimize(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    if not Config.AI_ENABLED:
        return jsonify({"error": "AI features are disabled. Set GROQ_API_KEY in your .env file."}), 503
    body = request.get_json(silent=True) or {}
    sql = (body.get("sql") or "").strip()[:5000]
    if not sql:
        return jsonify({"error": "No SQL to optimize."}), 400
    try:
        with activity_log.timed_event("ai_request", dataset_id=dataset_id, kind="sql_optimize"):
            schema = sql_engine.table_schema(dataset_id)
            optimized = ai_service.optimize_sql(sql, schema)
        return jsonify({"optimized_sql": optimized})
    except ai_service.AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502


# --------------------------------------------------------------------------
# API: AI Chat + Insights
# --------------------------------------------------------------------------

def _dataset_context_for(dataset_id: str) -> str:
    meta = storage.load_meta(dataset_id)
    df = storage.load_clean_df(dataset_id)
    sample_rows = df.head(5).fillna("").to_dict(orient="records")
    return ai_service.build_dataset_context(meta["profile"], sample_rows, meta.get("filename", "dataset"))


@app.route("/api/chat/<dataset_id>/sessions", methods=["GET"])
def api_chat_sessions_list(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    return jsonify({"chats": chat_store.list_chats(dataset_id)})


@app.route("/api/chat/<dataset_id>/sessions", methods=["POST"])
def api_chat_sessions_create(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    chat = chat_store.create_chat(dataset_id)
    return jsonify(chat)


@app.route("/api/chat/<dataset_id>/sessions/<chat_id>", methods=["GET"])
def api_chat_session_get(dataset_id, chat_id):
    chat = chat_store.get_chat(dataset_id, chat_id)
    if chat is None:
        return jsonify({"error": "Chat not found."}), 404
    return jsonify(chat)


@app.route("/api/chat/<dataset_id>/sessions/<chat_id>", methods=["PATCH"])
def api_chat_session_rename(dataset_id, chat_id):
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    if not title:
        return jsonify({"error": "New title is required."}), 400
    chat = chat_store.rename_chat(dataset_id, chat_id, title)
    if chat is None:
        return jsonify({"error": "Chat not found."}), 404
    return jsonify(chat)


@app.route("/api/chat/<dataset_id>/sessions/<chat_id>", methods=["DELETE"])
def api_chat_session_delete(dataset_id, chat_id):
    deleted = chat_store.delete_chat(dataset_id, chat_id)
    return jsonify({"deleted": deleted})


@app.route("/api/chat/<dataset_id>", methods=["POST"])
@rate_limit(max_calls=30, window_seconds=60)
def api_chat(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    if not Config.AI_ENABLED:
        return jsonify({"error": "AI features are disabled. Set GROQ_API_KEY in your .env file."}), 503

    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()[:2000]
    chat_id = body.get("chat_id")
    history = body.get("history") or []
    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    # If no session was persisted client-side, degrade gracefully to the
    # stateless behavior (history passed in the request body) so the chat
    # still works even if chat_store has an issue.
    if chat_id and chat_store.get_chat(dataset_id, chat_id) is None:
        chat_id = None

    try:
        with activity_log.timed_event("ai_request", dataset_id=dataset_id, kind="chat"):
            context = _dataset_context_for(dataset_id)
            if chat_id:
                chat_store.append_message(dataset_id, chat_id, "user", question)
                stored = chat_store.get_chat(dataset_id, chat_id)
                history = [{"role": m["role"], "content": m["content"]} for m in stored["messages"][:-1]]
            answer = ai_service.chat_with_dataset(question, context, history)
            if chat_id:
                chat_store.append_message(dataset_id, chat_id, "assistant", answer)
                updated_history = [{"role": m["role"], "content": m["content"]}
                                    for m in chat_store.get_chat(dataset_id, chat_id)["messages"]]
            else:
                updated_history = history + [{"role": "user", "content": question},
                                              {"role": "assistant", "content": answer}]
            followups = ai_service.suggest_followups(context, updated_history)
        return jsonify({"answer": answer, "followups": followups, "chat_id": chat_id})
    except ai_service.AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/insights/<dataset_id>", methods=["POST"])
@rate_limit(max_calls=10, window_seconds=60)
def api_insights(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    if not Config.AI_ENABLED:
        return jsonify({"error": "AI features are disabled. Set GROQ_API_KEY in your .env file."}), 503

    try:
        with activity_log.timed_event("ai_request", dataset_id=dataset_id, kind="executive_summary"):
            context = _dataset_context_for(dataset_id)
            summary = ai_service.generate_executive_summary(context)
            storage.update_meta(dataset_id, {"ai_executive_summary": summary})
        return jsonify({"summary": summary})
    except ai_service.AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/explain-chart/<dataset_id>", methods=["POST"])
@rate_limit(max_calls=30, window_seconds=60)
def api_explain_chart(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    if not Config.AI_ENABLED:
        return jsonify({"error": "AI features are disabled. Set GROQ_API_KEY in your .env file."}), 503

    body = request.get_json(silent=True) or {}
    chart_title = (body.get("chart_title") or "").strip()
    if not chart_title:
        return jsonify({"error": "Missing chart_title."}), 400

    try:
        with activity_log.timed_event("ai_request", dataset_id=dataset_id, kind="chart_explain"):
            context = _dataset_context_for(dataset_id)
            explanation = ai_service.explain_chart(chart_title, context)
        return jsonify({"explanation": explanation})
    except ai_service.AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502


# --------------------------------------------------------------------------
# API: Excel Dashboard export
# --------------------------------------------------------------------------

@app.route("/api/export/excel/<dataset_id>")
def api_export_excel(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404

    meta = storage.load_meta(dataset_id)
    raw_df = storage.load_raw_df(dataset_id)
    clean_df = storage.load_clean_df(dataset_id)
    profile = meta["profile"]

    ai_qa_pairs = None
    if Config.AI_ENABLED and request.args.get("ai") != "0":
        try:
            ai_qa_pairs = _generate_ai_qa_pairs(dataset_id, clean_df)
        except ai_service.AIServiceError:
            logger.warning("AI Search sheet falling back to deterministic Q&A for %s", dataset_id)

    wb = excel_export.build_workbook(
        raw_df=raw_df, clean_df=clean_df, profile=profile,
        cleaning_log=meta.get("cleaning_log", []), filename=meta.get("filename", "dataset"),
        ai_qa_pairs=ai_qa_pairs, business_insights=business_insights_utils.build_business_insights(clean_df),
    )
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    safe_name = Path(meta.get("filename", "dataset")).stem
    return send_file(
        buffer, as_attachment=True, download_name=f"{safe_name}_dashboard.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _generate_ai_qa_pairs(dataset_id: str, df) -> list[dict]:
    """A short, fixed set of high-value business questions (services/prompts.py),
    answered once by the AI at export time and baked into the AI Search sheet."""
    context = _dataset_context_for(dataset_id)
    pairs = []
    for q in prompts.EXCEL_SEARCH_QUESTIONS:
        try:
            answer = ai_service.chat_with_dataset(q, context)
        except ai_service.AIServiceError as exc:
            answer = f"(Could not generate: {exc})"
        pairs.append({"question": q, "answer": answer})
    return pairs


# --------------------------------------------------------------------------
# API: Reports (Markdown / HTML / PDF)
# --------------------------------------------------------------------------

@app.route("/api/report/<dataset_id>/json")
def api_report_json(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    meta = storage.load_meta(dataset_id)
    df = storage.load_clean_df(dataset_id)
    kpi_cards = chart_utils.build_kpi_cards(df)
    insights = business_insights_utils.build_business_insights(df)

    payload = {
        "filename": meta.get("filename"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": meta["profile"],
        "kpi_cards": kpi_cards,
        "business_insights": insights,
        "cleaning_log": meta.get("cleaning_log", []),
        "ai_executive_summary": meta.get("ai_executive_summary"),
    }
    safe_name = Path(meta.get("filename", "dataset")).stem
    return Response(
        json.dumps(payload, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={safe_name}_export.json"},
    )


@app.route("/api/report/<dataset_id>/markdown")
def api_report_markdown(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    meta = storage.load_meta(dataset_id)
    df = storage.load_clean_df(dataset_id)
    kpi_cards = chart_utils.build_kpi_cards(df)

    md = reports.generate_markdown_report(
        filename=meta.get("filename", "dataset"), profile=meta["profile"],
        cleaning_log=meta.get("cleaning_log", []), kpi_cards=kpi_cards,
        ai_summary=meta.get("ai_executive_summary"),
    )
    safe_name = Path(meta.get("filename", "dataset")).stem
    return Response(md, mimetype="text/markdown",
                     headers={"Content-Disposition": f"attachment; filename={safe_name}_report.md"})


@app.route("/api/report/<dataset_id>/html")
def api_report_html(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    meta = storage.load_meta(dataset_id)
    df = storage.load_clean_df(dataset_id)
    kpi_cards = chart_utils.build_kpi_cards(df)
    dashboard_charts = cache.get_or_compute(f"chart_images:{dataset_id}", lambda: chart_images.build_dashboard_chart_images(df))

    html = reports.generate_html_report(
        filename=meta.get("filename", "dataset"), profile=meta["profile"],
        cleaning_log=meta.get("cleaning_log", []), kpi_cards=kpi_cards,
        charts=dashboard_charts, ai_summary=meta.get("ai_executive_summary"),
    )
    safe_name = Path(meta.get("filename", "dataset")).stem
    download = request.args.get("download") == "1"
    headers = {"Content-Disposition": f"attachment; filename={safe_name}_report.html"} if download else {}
    return Response(html, mimetype="text/html", headers=headers)


@app.route("/api/report/<dataset_id>/pdf")
def api_report_pdf(dataset_id):
    if not storage.dataset_exists(dataset_id):
        return jsonify({"error": "Dataset not found."}), 404
    meta = storage.load_meta(dataset_id)
    df = storage.load_clean_df(dataset_id)
    kpi_cards = chart_utils.build_kpi_cards(df)

    try:
        pdf_bytes = pdf_report.generate_pdf_report(
            filename=meta.get("filename", "dataset"), df=df, profile=meta["profile"],
            cleaning_log=meta.get("cleaning_log", []), kpi_cards=kpi_cards,
            ai_summary=meta.get("ai_executive_summary"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("PDF generation failed")
        return jsonify({"error": f"Could not generate PDF: {exc}"}), 500

    safe_name = Path(meta.get("filename", "dataset")).stem
    return send_file(
        io.BytesIO(pdf_bytes), as_attachment=True,
        download_name=f"{safe_name}_report.pdf", mimetype="application/pdf",
    )


@app.route("/admin/activity")
def admin_activity():
    if not Config.ADMIN_TOKEN:
        return jsonify({"error": "Admin activity log is disabled. Set ADMIN_TOKEN in your .env file to enable it."}), 404
    if request.args.get("token") != Config.ADMIN_TOKEN:
        return jsonify({"error": "Invalid or missing token."}), 403
    entries = activity_log.read_recent(limit=300)
    return render_template("admin_activity.html", entries=entries, token=Config.ADMIN_TOKEN)


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": f"File is too large. Max size is {Config.MAX_UPLOAD_MB} MB."}), 413


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=Config.DEBUG)
