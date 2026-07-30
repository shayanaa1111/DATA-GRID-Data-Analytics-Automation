"""
Persists AI Chat conversations per dataset so a person can leave the
AI Chat tab and come back to their history — one JSON file per chat
session under processed_data/<dataset_id>/chats/.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from utils.storage import dataset_dir

MAX_MESSAGES = 200


def _chats_dir(dataset_id: str) -> Path:
    d = dataset_dir(dataset_id) / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chat_path(dataset_id: str, chat_id: str) -> Path:
    return _chats_dir(dataset_id) / f"{chat_id}.json"


def create_chat(dataset_id: str, title: str = "New chat") -> dict:
    chat_id = uuid.uuid4().hex[:10]
    chat = {
        "id": chat_id,
        "title": title,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "messages": [],
    }
    _save(dataset_id, chat)
    return chat


def list_chats(dataset_id: str) -> list[dict]:
    chats = []
    for path in _chats_dir(dataset_id).glob("*.json"):
        try:
            with open(path) as f:
                chat = json.load(f)
            chats.append({
                "id": chat["id"], "title": chat.get("title", "Chat"),
                "updated_at": chat.get("updated_at"), "message_count": len(chat.get("messages", [])),
            })
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    chats.sort(key=lambda c: c.get("updated_at") or "", reverse=True)
    return chats


def get_chat(dataset_id: str, chat_id: str) -> dict | None:
    path = _chat_path(dataset_id, chat_id)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def append_message(dataset_id: str, chat_id: str, role: str, content: str) -> dict | None:
    chat = get_chat(dataset_id, chat_id)
    if chat is None:
        return None
    chat["messages"].append({"role": role, "content": content, "at": datetime.now(timezone.utc).isoformat()})
    chat["messages"] = chat["messages"][-MAX_MESSAGES:]
    chat["updated_at"] = datetime.now(timezone.utc).isoformat()
    # Auto-title from the first user message, so the sidebar isn't full of "New chat"
    if chat["title"] == "New chat" and role == "user":
        chat["title"] = (content[:48] + "…") if len(content) > 48 else content
    _save(dataset_id, chat)
    return chat


def rename_chat(dataset_id: str, chat_id: str, new_title: str) -> dict | None:
    chat = get_chat(dataset_id, chat_id)
    if chat is None:
        return None
    chat["title"] = new_title.strip()[:80] or chat["title"]
    chat["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save(dataset_id, chat)
    return chat


def delete_chat(dataset_id: str, chat_id: str) -> bool:
    path = _chat_path(dataset_id, chat_id)
    if path.exists():
        path.unlink()
        return True
    return False


def _save(dataset_id: str, chat: dict) -> None:
    with open(_chat_path(dataset_id, chat["id"]), "w") as f:
        json.dump(chat, f, default=str)
