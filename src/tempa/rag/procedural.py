from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from tempa.rag.ingest import ingest_text
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()

KINDS = frozenset({"preference", "correction", "fact", "person", "project", "decision"})

PREFERENCE_PATTERNS = [
    re.compile(r"from now on[,.]?\s*(.+)", re.I),
    re.compile(r"always\s+(.+)", re.I),
    re.compile(r"never\s+(.+)", re.I),
    re.compile(r"remember to\s+(.+)", re.I),
    re.compile(r"prefer(?:ence)?\s+(?:that\s+)?(.+)", re.I),
]

CORRECTION_PATTERNS = [
    re.compile(r"^(?:no|nope)[,.]?\s+(.+)", re.I),
    re.compile(r"^(?:actually|instead)[,.]?\s+(.+)", re.I),
    re.compile(r"^(?:don'?t|do not)\s+(.+)", re.I),
    re.compile(r"^(?:wrong[,.]?\s+)(.+)", re.I),
    re.compile(r"not\s+(.+?),\s*(.+)", re.I),
    re.compile(r"instead of\s+(.+?),\s*(.+)", re.I),
]

_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")
_REPO_RE = re.compile(r"(?:github\.com/)?([\w.\-]+/[\w.\-]+)", re.I)

_TOPIC_STOP = frozenset(
    "a an the to for of and or do dont don't please just about with from".split()
)


def _memory_dir() -> Any:
    path = get_settings().sessions_dir / "memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _durable_path() -> Any:
    return _memory_dir() / "durable.json"


def _store_path() -> Any:
    """Backward-compat alias used by older tests/callers."""
    return _durable_path()


def _legacy_path() -> Any:
    return _memory_dir() / "procedural.json"


def _open_clarifications_path() -> Any:
    return _memory_dir() / "open_clarifications.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _topic_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9@./_-]+", _normalize_text(text))
    return {w for w in words if w not in _TOPIC_STOP and len(w) > 2}


def _migrate_legacy_unlocked(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize legacy preference records and durable.json shape."""
    out: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or raw.get("rule") or "").strip()
        if not text:
            continue
        kind = str(raw.get("kind") or "preference").lower()
        if kind not in KINDS:
            kind = "preference"
        record = {
            "id": str(raw.get("id") or uuid.uuid4()),
            "kind": kind,
            "text": text,
            "rule": text,  # backward compat for API/dashboard
            "source": str(raw.get("source") or "manual"),
            "tags": list(raw.get("tags") or []),
            "created_at": str(raw.get("created_at") or _now()),
            "superseded_by": raw.get("superseded_by") or None,
        }
        out.append(record)
    return out


def _read_all_unlocked() -> list[dict[str, Any]]:
    durable = _durable_path()
    legacy = _legacy_path()
    path = durable if durable.exists() else legacy
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else []
    except Exception:
        return []
    return _migrate_legacy_unlocked(items)


def _write_all_unlocked(items: list[dict[str, Any]]) -> None:
    _memory_dir()
    payload = []
    for p in items:
        text = str(p.get("text") or p.get("rule") or "")
        payload.append(
            {
                "id": p["id"],
                "kind": p.get("kind") or "preference",
                "text": text,
                "rule": text,
                "source": p.get("source") or "manual",
                "tags": list(p.get("tags") or []),
                "created_at": p.get("created_at") or _now(),
                "superseded_by": p.get("superseded_by"),
            }
        )
    path = _durable_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _active_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in items if not p.get("superseded_by")]


def _find_conflicts(items: list[dict[str, Any]], text: str, kind: str) -> list[str]:
    """Return ids of active prefs/corrections that share topic tokens with the new text."""
    if kind not in ("preference", "correction"):
        return []
    new_tokens = _topic_tokens(text)
    if len(new_tokens) < 2:
        return []
    conflicts: list[str] = []
    for item in _active_items(items):
        if item.get("kind") not in ("preference", "correction"):
            continue
        old_tokens = _topic_tokens(str(item.get("text") or ""))
        overlap = new_tokens & old_tokens
        if len(overlap) >= 2:
            conflicts.append(str(item["id"]))
    return conflicts


def _is_near_duplicate(items: list[dict[str, Any]], text: str, kind: str) -> bool:
    norm = _normalize_text(text)
    for item in _active_items(items):
        if item.get("kind") != kind:
            continue
        if _normalize_text(str(item.get("text") or "")) == norm:
            return True
    return False


def add_durable(
    text: str,
    *,
    kind: str = "preference",
    source: str = "manual",
    tags: list[str] | None = None,
    supersede_ids: list[str] | None = None,
) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("empty text")
    kind = (kind or "preference").lower()
    if kind not in KINDS:
        kind = "fact"
    tag_list = list(tags or [])

    with _lock:
        items = _read_all_unlocked()
        if _is_near_duplicate(items, text, kind):
            for item in _active_items(items):
                if item.get("kind") == kind and _normalize_text(str(item.get("text") or "")) == _normalize_text(
                    text
                ):
                    return item

        record_id = str(uuid.uuid4())
        to_supersede = list(supersede_ids or []) or _find_conflicts(items, text, kind)
        for old_id in to_supersede:
            for item in items:
                if item.get("id") == old_id and not item.get("superseded_by"):
                    item["superseded_by"] = record_id

        record = {
            "id": record_id,
            "kind": kind,
            "text": text,
            "rule": text,
            "source": source,
            "tags": tag_list,
            "created_at": _now(),
            "superseded_by": None,
        }
        items.append(record)
        _write_all_unlocked(items)

    chroma_tags = ["knowledge", kind, *tag_list]
    if kind == "preference":
        chroma_tags = ["preference", *tag_list]
    ingest_text(
        text,
        tool="procedural",
        source=source,
        tags=chroma_tags,
        memory_class="semantic" if kind in ("fact", "person", "project", "decision") else "",
    )
    return record


def add_preference(
    rule: str,
    *,
    source: str = "manual",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return add_durable(rule, kind="preference", source=source, tags=tags)


def add_fact(
    text: str,
    *,
    kind: str = "fact",
    source: str = "manual",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    if kind not in KINDS:
        kind = "fact"
    return add_durable(text, kind=kind, source=source, tags=tags)


def list_durable(*, kinds: list[str] | None = None, include_superseded: bool = False) -> list[dict[str, Any]]:
    with _lock:
        items = _read_all_unlocked()
    if not include_superseded:
        items = _active_items(items)
    if kinds:
        wanted = {k.lower() for k in kinds}
        items = [p for p in items if p.get("kind") in wanted]
    return list(items)


def list_preferences() -> list[dict[str, Any]]:
    return list_durable(kinds=["preference", "correction"], include_superseded=False)


def delete_preference(pref_id: str) -> bool:
    with _lock:
        items = _read_all_unlocked()
        filtered = [p for p in items if p.get("id") != pref_id]
        if len(filtered) == len(items):
            return False
        _write_all_unlocked(filtered)
        return True


def supersede(old_id: str, new_id: str) -> bool:
    with _lock:
        items = _read_all_unlocked()
        found = False
        for item in items:
            if item.get("id") == old_id:
                item["superseded_by"] = new_id
                found = True
                break
        if found:
            _write_all_unlocked(items)
        return found


def format_durable_for_prompt(
    *,
    kinds: list[str] | None = None,
    limit: int = 12,
    query: str = "",
) -> str:
    kinds = kinds or ["preference", "correction", "person", "project", "decision", "fact"]
    items = list_durable(kinds=kinds)
    if not items:
        return ""
    if query.strip():
        q_tokens = _topic_tokens(query)
        if q_tokens:
            scored = []
            for item in items:
                overlap = len(q_tokens & _topic_tokens(str(item.get("text") or "")))
                scored.append((overlap, item))
            scored.sort(key=lambda x: (x[0], x[1].get("created_at") or ""), reverse=True)
            # Keep some overlap hits first, then fall back to recent
            with_overlap = [it for score, it in scored if score > 0]
            without = [it for score, it in scored if score == 0]
            items = (with_overlap + without)[:limit]
        else:
            items = items[-limit:]
    else:
        items = items[-limit:]

    by_kind: dict[str, list[str]] = {}
    for item in items:
        kind = str(item.get("kind") or "fact")
        by_kind.setdefault(kind, []).append(f"- {item.get('text')}")

    sections: list[str] = []
    labels = {
        "preference": "User preferences",
        "correction": "Corrections to follow",
        "person": "People",
        "project": "Projects",
        "decision": "Decisions",
        "fact": "Org facts",
    }
    for kind in kinds:
        lines = by_kind.get(kind) or []
        if lines:
            sections.append(f"{labels.get(kind, kind.title())}:\n" + "\n".join(lines))
    if not sections:
        return ""
    return "Durable memory:\n" + "\n\n".join(sections)


def format_preferences_for_prompt(limit: int = 10, query: str = "") -> str:
    return format_durable_for_prompt(
        kinds=["preference", "correction", "person", "project", "decision", "fact"],
        limit=limit,
        query=query,
    )


def extract_preference_from_message(message: str) -> str | None:
    for pat in PREFERENCE_PATTERNS:
        match = pat.search(message)
        if match:
            return match.group(1).strip().rstrip(".")
    return None


def extract_correction_from_message(message: str) -> tuple[str, str] | None:
    """Return (kind, text) for an explicit correction, or None."""
    text = (message or "").strip()
    if not text:
        return None
    for pat in CORRECTION_PATTERNS:
        match = pat.search(text)
        if not match:
            continue
        if pat.pattern.startswith("not\\s+") or "instead of" in pat.pattern:
            # not X, Y  / instead of X, Y → prefer Y as the standing rule
            corrected = match.group(2).strip().rstrip(".")
            if corrected:
                return ("correction", corrected)
        else:
            body = match.group(1).strip().rstrip(".")
            if body:
                return ("correction", body)
    return None


def lookup_durable_answer(query: str, *, kinds: list[str] | None = None) -> str | None:
    """Return best durable text matching query tokens, if any."""
    q_tokens = _topic_tokens(query)
    if not q_tokens:
        return None
    best: tuple[int, str] | None = None
    for item in list_durable(kinds=kinds):
        text = str(item.get("text") or "")
        overlap = len(q_tokens & _topic_tokens(text))
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, text)
    return best[1] if best else None


def find_person_email(name_hint: str) -> str | None:
    hint = _normalize_text(name_hint)
    if not hint:
        return None
    for item in list_durable(kinds=["person", "fact"]):
        text = str(item.get("text") or "")
        if hint not in _normalize_text(text):
            continue
        email = _EMAIL_RE.search(text)
        if email:
            return email.group(0)
    return None


def find_default_repo() -> str | None:
    for item in list_durable(kinds=["project", "fact", "preference"]):
        text = str(item.get("text") or "")
        m = _REPO_RE.search(text)
        if m and ("repo" in _normalize_text(text) or "github" in _normalize_text(text) or item.get("kind") == "project"):
            return m.group(1) if m.lastindex else m.group(0)
    return None


def maybe_llm_extract_durable(message: str, *, after_bot: bool = False) -> dict[str, Any] | None:
    """Optional LLM extract for short corrective / preference feedback."""
    text = (message or "").strip()
    if not text or len(text) > 400:
        return None
    lower = text.lower()
    looks_corrective = after_bot or any(
        lower.startswith(p) for p in ("no", "nope", "actually", "instead", "don't", "do not", "wrong")
    )
    looks_pref = any(k in lower for k in ("always", "never", "from now on", "prefer", "remember"))
    if not looks_corrective and not looks_pref:
        return None
    # Regex already handled — skip LLM
    if extract_preference_from_message(text) or extract_correction_from_message(text):
        return None
    try:
        from tempa.router.groq_router import get_router

        router = get_router()
        response = router.chat_completion(
            category="text",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract at most one durable learning from this user message. "
                        'Return JSON only: {"kind":"preference"|"correction"|"fact"|null,"text":"..."}. '
                        "Use null kind if nothing durable. Message:\n"
                        f"{text[:500]}"
                    ),
                }
            ],
            max_tokens=120,
            temperature=0.1,
        )
        raw = (response.choices[0].message.content or "").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        data = json.loads(raw[start : end + 1])
        kind = data.get("kind")
        body = str(data.get("text") or "").strip()
        if not kind or not body or kind not in KINDS:
            return None
        return add_durable(body, kind=str(kind), source="llm_extract", tags=["auto"])
    except Exception:
        logger.debug("LLM durable extract skipped", exc_info=True)
        return None


def maybe_capture_from_message(message: str, *, after_bot: bool = False) -> dict[str, Any] | None:
    correction = extract_correction_from_message(message)
    if correction:
        kind, body = correction
        record = add_durable(body, kind=kind, source="explicit", tags=["auto", "correction"])
        # Standing rule when correction implies always/never/from now on
        pref = extract_preference_from_message(body) or extract_preference_from_message(message)
        if pref and pref != body:
            add_preference(pref, source="explicit", tags=["auto", "from_correction"])
        elif any(k in body.lower() for k in ("always", "never", "from now on")):
            add_preference(body, source="explicit", tags=["auto", "from_correction"])
        return record

    rule = extract_preference_from_message(message)
    if rule:
        return add_preference(rule, source="explicit", tags=["auto"])

    return maybe_llm_extract_durable(message, after_bot=after_bot)


def capture_from_approval(action_type: str, payload: dict[str, Any]) -> None:
    if action_type == "email_send":
        to = str(payload.get("to", "")).strip()
        if payload.get("body_html") and to:
            add_preference(
                f"Use HTML format for emails to {to}",
                source="approval",
                tags=["email"],
            )
        elif to:
            add_preference(
                f"User approved sending email to {to}",
                source="approval",
                tags=["email"],
            )
    elif action_type == "whatsapp_send":
        number = str(payload.get("number", "")).strip()
        if number:
            add_preference(
                f"User approved WhatsApp messages to {number}",
                source="approval",
                tags=["whatsapp"],
            )


# --- Open clarifications (ask → answer → remember) ---


def _conversation_key(context: dict[str, Any] | None) -> str:
    ctx = dict(context or {})
    channel = str(ctx.get("channel") or "unknown")
    for key in (
        "slack_conversation_key",
        "slack_thread_ts",
        "thread_ts",
        "whatsapp_chat_id",
        "conversation_id",
        "session_id",
    ):
        val = str(ctx.get(key) or "").strip()
        if val:
            return f"{channel}:{val}"
    user = str(ctx.get("user_id") or ctx.get("slack_user_id") or "default")
    return f"{channel}:{user}"


def _read_open_unlocked() -> list[dict[str, Any]]:
    path = _open_clarifications_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_open_unlocked(items: list[dict[str, Any]]) -> None:
    path = _open_clarifications_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def register_open_clarification(
    question: str,
    *,
    slot: str = "general",
    context: dict[str, Any] | None = None,
    hint: str = "",
) -> dict[str, Any]:
    question = (question or "").strip()
    if not question:
        raise ValueError("empty question")
    record = {
        "id": str(uuid.uuid4()),
        "question": question,
        "slot": slot or "general",
        "hint": hint or "",
        "conversation_key": _conversation_key(context),
        "channel": str((context or {}).get("channel") or ""),
        "asked_at": _now(),
    }
    with _lock:
        items = [i for i in _read_open_unlocked() if i.get("conversation_key") != record["conversation_key"]]
        items.append(record)
        # Keep last 50 open slots
        _write_open_unlocked(items[-50:])
    return record


def get_open_clarification(context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    key = _conversation_key(context)
    with _lock:
        items = _read_open_unlocked()
    for item in reversed(items):
        if item.get("conversation_key") == key:
            return item
    return None


def clear_open_clarification(context: dict[str, Any] | None = None, *, clar_id: str = "") -> None:
    with _lock:
        items = _read_open_unlocked()
        if clar_id:
            items = [i for i in items if i.get("id") != clar_id]
        else:
            key = _conversation_key(context)
            items = [i for i in items if i.get("conversation_key") != key]
        _write_open_unlocked(items)


def _infer_slot_from_question(question: str) -> str:
    lower = (question or "").lower()
    if "email" in lower:
        return "email"
    if "repository" in lower or "github" in lower or "repo" in lower:
        return "repo"
    if "date" in lower or "time" in lower or "schedule" in lower:
        return "datetime"
    if "meet" in lower and "link" in lower:
        return "meet_url"
    if "jira" in lower or "issue key" in lower:
        return "jira_key"
    if "slack" in lower or "message" in lower or "channel" in lower:
        return "slack_recipient"
    if "path" in lower or "file" in lower:
        return "file_path"
    return "general"


def resolve_open_clarification(
    answer: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """If there is an open clarification for this conversation, store durable memory and clear it."""
    answer = (answer or "").strip()
    if not answer:
        return None
    open_q = get_open_clarification(context)
    if not open_q:
        return None

    slot = str(open_q.get("slot") or _infer_slot_from_question(str(open_q.get("question") or "")))
    hint = str(open_q.get("hint") or "")
    question = str(open_q.get("question") or "")
    record: dict[str, Any] | None = None

    email = _EMAIL_RE.search(answer)
    if slot == "email" or email:
        addr = email.group(0) if email else answer.strip()
        name = hint or ""
        if not name:
            m = re.search(r"mentioned\s+(\w+)", question, re.I)
            if m:
                name = m.group(1)
        text = f"{name} email is {addr}".strip() if name else f"Email address: {addr}"
        tags = ["clarification", "email"]
        try:
            from tempa.channels.contacts.linker import lookup_identity

            ident = lookup_identity(name or addr)
            if ident and ident.get("id"):
                tags.append(f"identity:{ident['id']}")
        except Exception:
            pass
        record = add_durable(text, kind="person", source="clarification", tags=tags)
    elif slot == "repo":
        m = _REPO_RE.search(answer)
        repo = m.group(1) if m else answer.strip()
        record = add_durable(
            f"Default repository for scans: {repo}",
            kind="project",
            source="clarification",
            tags=["clarification", "repo"],
        )
    elif any(k in answer.lower() for k in ("always", "never", "from now on", "prefer")):
        pref = extract_preference_from_message(answer) or answer
        record = add_preference(pref, source="clarification", tags=["clarification"])
    else:
        record = add_durable(
            f"Regarding '{question[:80]}': {answer}",
            kind="fact",
            source="clarification",
            tags=["clarification", slot],
        )

    clear_open_clarification(context, clar_id=str(open_q.get("id") or ""))
    return record
