from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from tempa.channels.whatsapp.numbers import normalize_phone, resolve_whatsapp_jid
from tempa.settings import get_settings


def _name_matches(query: str, contact_name: str) -> bool:
    words = [w for w in re.split(r"\s+", query.lower()) if len(w) > 1]
    name = contact_name.lower()
    return all(w in name for w in words) if words else query.lower() in name


def _aliases_path() -> Path:
    path = get_settings().sessions_dir / "whatsapp" / "name_aliases.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_name_aliases() -> dict[str, str]:
    path = _aliases_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k).lower(): normalize_phone(str(v)) for k, v in data.items() if v and not str(k).endswith("__chat")}
    except Exception:
        return {}


def save_name_alias(name: str, phone: str) -> None:
    key = name.strip().lower()
    phone = normalize_phone(phone)
    if not key or not phone:
        return
    aliases = _load_name_aliases()
    existing = aliases.get(key, "")
    # ponytail: explicit alias wins — don't overwrite a different saved number
    if existing and existing != phone:
        return
    aliases[key] = phone
    _aliases_path().write_text(json.dumps(aliases, ensure_ascii=False, indent=2), encoding="utf-8")


def _chat_alias_key(name: str) -> str:
    return f"{name.strip().lower()}__chat"


def _load_chat_phone(name: str) -> str:
    path = _aliases_path()
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return normalize_phone(str(data.get(_chat_alias_key(name)) or ""))
    except Exception:
        return ""


def save_chat_phone_alias(name: str, phone: str) -> None:
    key = _chat_alias_key(name)
    phone = normalize_phone(phone)
    if not key or not phone:
        return
    path = _aliases_path()
    data: dict[str, str] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = {str(k): str(v) for k, v in raw.items()}
        except Exception:
            pass
    if data.get(key) == phone:
        return
    data[key] = phone
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_phone(text: str) -> str:
    compact = re.sub(r"[^\d+]", " ", text)
    for chunk in re.findall(r"\+?\d[\d\s\-]{8,16}\d", compact):
        digits = re.sub(r"\D", "", chunk)
        if len(digits) < 10:
            continue
        normalized = normalize_phone(digits)
        if normalized.startswith("92") and len(normalized) >= 12:
            return normalized
    match = re.search(r"\b(92\d{9,11}|0\d{10,11})\b", re.sub(r"[\s\-]", "", text))
    if not match:
        return ""
    return normalize_phone(match.group(1))


def _format_phone_display(phone: str) -> str:
    phone = normalize_phone(phone)
    if phone.startswith("92") and len(phone) == 12:
        return f"+{phone[:2]} {phone[2:5]} {phone[5:]}"
    return f"+{phone}" if phone else ""


def _display_name_for_phone(phone: str, fallback: str) -> str:
    phone = normalize_phone(phone)
    for name, mapped in _load_name_aliases().items():
        if mapped == phone:
            return name.title()
    return fallback


def _resolve_contact_phone(name: str) -> tuple[str, str]:
    from tempa.channels.contacts.store import search_contacts

    alias = _load_name_aliases().get(name.strip().lower(), "")
    if alias:
        hits = search_contacts(name, limit=8)
        display = next(
            (str(h.get("name") or "") for h in hits if _name_matches(name, str(h.get("name") or ""))),
            name.title(),
        )
        return alias, display or name.title()

    try:
        from tempa.rag.search import search_memory

        for row in search_memory(f"{name} whatsapp phone", top_k=5):
            phone = _extract_phone(str(row.get("content") or ""))
            if phone:
                return phone, name.title()
    except Exception:
        pass

    hits = search_contacts(name, limit=8)
    for hit in hits:
        phone = normalize_phone(str(hit.get("phone") or ""))
        if not phone:
            continue
        if _name_matches(name, str(hit.get("name") or "")):
            return phone, str(hit.get("name") or name.title())
    for hit in hits:
        phone = normalize_phone(str(hit.get("phone") or ""))
        if phone:
            return phone, str(hit.get("name") or name.title())
    return "", name.title()


def _format_ts(value: str | int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return ""


def _iter_conversation_rows() -> Iterator[dict[str, Any]]:
    path = get_settings().sessions_dir / "whatsapp" / "conversation.jsonl"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            yield row


def _conversation_for_chat(chat_id: str, phone: str = "", *, limit: int = 100) -> list[dict[str, Any]]:
    phone_norm = normalize_phone(phone)
    phone_tail = phone_norm[-10:] if len(phone_norm) >= 10 else phone_norm
    rows: list[dict[str, Any]] = []
    for row in _iter_conversation_rows():
        row_chat = str(row.get("chat_id") or "")
        row_from = normalize_phone(str(row.get("from") or ""))
        row_chat_phone = normalize_phone(row_chat.split("@")[0])
        matched = False
        if chat_id and row_chat == chat_id:
            matched = True
        elif phone_tail and (
            (row_from and row_from.endswith(phone_tail))
            or (row_chat_phone and row_chat_phone.endswith(phone_tail))
        ):
            matched = True
        if not matched:
            continue
        # ponytail: drop other people's lines mis-tagged in this chat (user + owner)
        if phone_tail and row_from:
            if str(row.get("role") or "") in ("user", "owner") and not row_from.endswith(phone_tail):
                continue
        rows.append(row)
    return rows[-limit:]


async def _resolve_chat_target(name: str, client: Any, *, query_text: str = "") -> tuple[str, str, str]:
    from tempa.channels.whatsapp.peers import find_whatsapp_peer, remember_whatsapp_peer

    phone_hint = _extract_phone(query_text)
    if phone_hint:
        jid = resolve_whatsapp_jid(phone_hint)
        return jid, phone_hint, _display_name_for_phone(phone_hint, name.title())

    alias_phone = _load_name_aliases().get(name.strip().lower(), "")
    if alias_phone:
        return resolve_whatsapp_jid(alias_phone), alias_phone, name.title()

    peer = find_whatsapp_peer(name)
    if peer:
        return (
            str(peer.get("jid") or ""),
            normalize_phone(str(peer.get("phone") or "")),
            str(peer.get("push_name") or name.title()),
        )

    phone, contact_name = _resolve_contact_phone(name)
    if phone:
        return resolve_whatsapp_jid(phone), phone, contact_name

    try:
        matches = await client.match_contacts(name)
    except Exception:
        matches = []
    if len(matches) == 1:
        hit = matches[0]
        return str(hit.get("jid") or ""), normalize_phone(str(hit.get("phone") or "")), str(hit.get("pushName") or contact_name)
    if len(matches) > 1:
        exact = [m for m in matches if _name_matches(name, str(m.get("pushName") or ""))]
        if len(exact) == 1:
            hit = exact[0]
            return str(hit.get("jid") or ""), normalize_phone(str(hit.get("phone") or "")), str(hit.get("pushName") or contact_name)

    try:
        raw = await client.fetch_contact_history(hint=name, limit=1)
        jid = str(raw.get("jid") or "")
        if jid:
            contact = str(raw.get("contact") or contact_name)
            phone = normalize_phone(jid.split("@")[0])
            remember_whatsapp_peer(push_name=contact, from_number=phone, chat_id=jid)
            return jid, phone, contact
    except Exception:
        pass

    return "", "", contact_name


def _rows_to_messages(rows: list[dict[str, Any]], contact: str, phone: str = "") -> list[dict[str, Any]]:
    phone_tail = normalize_phone(phone)[-10:] if phone else ""
    out: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        role = str(row.get("role") or "user")
        row_from = normalize_phone(str(row.get("from") or ""))
        if role == "user":
            speaker = contact if not phone_tail or row_from.endswith(phone_tail) else contact
        else:
            speaker = "you"
        out.append(
            {
                "role": role,
                "from": speaker,
                "text": text,
                "timestamp": _format_ts(row.get("timestamp")),
            }
        )
    return out


def _collect_chat_targets(
    name: str,
    primary_phone: str,
    primary_jid: str,
) -> list[tuple[str, str]]:
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []

    def add(phone: str, jid: str = "") -> None:
        phone = normalize_phone(phone)
        if not phone or phone in seen:
            return
        seen.add(phone)
        targets.append((phone, jid or resolve_whatsapp_jid(phone)))

    add(primary_phone, primary_jid)
    chat_phone = _load_chat_phone(name)
    if chat_phone:
        add(chat_phone)

    from tempa.channels.whatsapp.peers import find_all_peers_matching

    for peer in find_all_peers_matching(name):
        add(str(peer.get("phone") or ""), str(peer.get("jid") or ""))

    return targets


async def _load_chat_from_target(
    client: Any,
    *,
    name: str,
    contact: str,
    phone: str,
    jid: str,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str, str]:
    local_rows = _conversation_for_chat(jid, phone, limit=max(limit, 100))
    local_messages = _rows_to_messages(local_rows, contact, phone)
    inbound = [m for m in local_messages if m.get("role") == "user"]

    live_messages: list[dict[str, Any]] = []
    resolved_jid = jid
    try:
        raw = await client.fetch_contact_history(hint=name, number=phone or None, jid=jid or None, limit=limit)
        resolved_jid = str(raw.get("jid") or jid or "")
        for msg in raw.get("messages") or []:
            text = str(msg.get("text") or "").strip()
            if not text:
                continue
            live_messages.append(
                {
                    "role": "assistant" if msg.get("fromMe") else "user",
                    "from": contact if not msg.get("fromMe") else "you",
                    "text": text,
                    "timestamp": _format_ts(msg.get("timestamp")),
                }
            )
    except Exception:
        pass

    messages = live_messages or local_messages
    inbound = [m for m in messages if m.get("role") == "user"] if live_messages else inbound
    return local_rows, local_messages, messages, resolved_jid, phone


async def lookup_contact_messages(name: str, *, limit: int = 50, query_text: str = "") -> dict[str, Any]:
    from tempa.channels.whatsapp.client import WhatsAppBridgeClient
    from tempa.channels.whatsapp.peers import remember_whatsapp_peer

    client = WhatsAppBridgeClient()
    jid, phone, contact = await _resolve_chat_target(name, client, query_text=query_text or name)

    if not jid and not phone:
        matches: list[dict[str, Any]] = []
        try:
            matches = await client.match_contacts(name)
        except Exception:
            pass
        if matches:
            options = ", ".join(
                f"{m.get('pushName') or m.get('phone') or m.get('jid')}" for m in matches[:5]
            )
            return {
                "status": "error",
                "reason": f"Multiple WhatsApp contacts match '{name}': {options}. Be more specific or include a phone number.",
            }
        return {
            "status": "error",
            "reason": (
                f"Could not find WhatsApp chat for '{name}'. "
                "Try their phone number (e.g. 923…), sync Google contacts with their number, "
                "or wait until they message you on WhatsApp so Tempa learns their name."
            ),
        }

    if not jid and phone:
        jid = resolve_whatsapp_jid(phone)

    contact_phone = phone
    best_messages: list[dict[str, Any]] = []
    best_inbound: list[dict[str, Any]] = []
    best_jid = jid
    best_chat_phone = phone

    for try_phone, try_jid in _collect_chat_targets(name, phone, jid):
        _, _, messages, resolved_jid, used_phone = await _load_chat_from_target(
            client,
            name=name,
            contact=contact,
            phone=try_phone,
            jid=try_jid,
            limit=limit,
        )
        inbound = [m for m in messages if m.get("role") == "user"]
        if inbound or any(m.get("role") == "user" for m in messages):
            best_messages = messages
            best_inbound = inbound
            best_jid = resolved_jid
            best_chat_phone = used_phone
            if used_phone != contact_phone:
                save_chat_phone_alias(name, used_phone)
            break

    if best_jid and contact:
        remember_whatsapp_peer(push_name=contact, from_number=best_chat_phone, chat_id=best_jid)

    if not best_inbound and not any(m.get("role") == "user" for m in best_messages):
        display = _format_phone_display(contact_phone)
        phone_note = f" ({display})" if display else ""
        return {
            "status": "ok",
            "contact": contact,
            "phone": contact_phone,
            "jid": jid,
            "messages": best_messages,
            "latest_message": "",
            "summary": (
                f"I found **{contact}** on WhatsApp{phone_note}, but Tempa has no stored messages "
                f"from that chat yet. Once they message your linked WhatsApp account — or you forward "
                f"a chat here — I'll read and summarize their thread."
            ),
            "source": "whatsapp_history",
        }

    latest_row = best_inbound[-1] if best_inbound else best_messages[-1]
    latest_text = str(latest_row.get("text") or "")
    if contact_phone and name.strip():
        save_name_alias(name, contact_phone)
    return {
        "status": "ok",
        "contact": contact,
        "phone": contact_phone,
        "chat_phone": best_chat_phone,
        "jid": best_jid,
        "latest_message": latest_text,
        "timestamp": str(latest_row.get("timestamp") or ""),
        "messages": best_messages[-limit:],
        "source": "whatsapp_history",
    }
