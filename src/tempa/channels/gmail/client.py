from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Full mailbox access: read, compose, send, modify labels, delete.
# contacts.readonly enables Google People sync for name→email invites.
DEFAULT_SCOPES: tuple[str, ...] = (
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/contacts.readonly",
)


@dataclass(frozen=True)
class GmailMessage:
    id: str
    thread_id: str
    subject: str
    sender: str
    to: str
    date: str
    snippet: str
    body_text: str
    label_ids: list[str]
    raw: dict[str, Any]


def _header(headers: list[dict[str, str]] | None, name: str) -> str:
    if not headers:
        return ""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_body_data(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_body(payload: dict[str, Any]) -> str:
    mime = payload.get("mimeType", "")
    body = payload.get("body") or {}
    data = body.get("data")
    if data and mime.startswith("text/plain"):
        return _decode_body_data(data)

    parts = payload.get("parts") or []
    plain = ""
    html = ""
    for part in parts:
        part_mime = part.get("mimeType", "")
        part_body = part.get("body") or {}
        part_data = part_body.get("data")
        if part_data:
            decoded = _decode_body_data(part_data)
            if part_mime.startswith("text/plain") and not plain:
                plain = decoded
            elif part_mime.startswith("text/html") and not html:
                html = decoded
        nested = _extract_body(part)
        if nested and not plain:
            plain = nested
    if plain:
        return plain
    if html:
        return re.sub(r"<[^>]+>", " ", html)
    return ""


def _parse_message(raw: dict[str, Any]) -> GmailMessage:
    payload = raw.get("payload") or {}
    headers = payload.get("headers") or []
    return GmailMessage(
        id=str(raw.get("id", "")),
        thread_id=str(raw.get("threadId", "")),
        subject=_header(headers, "Subject"),
        sender=_header(headers, "From"),
        to=_header(headers, "To"),
        date=_header(headers, "Date"),
        snippet=str(raw.get("snippet", "")),
        body_text=_extract_body(payload),
        label_ids=list(raw.get("labelIds") or []),
        raw=raw,
    )


class GmailClient:
    def __init__(self, creds: Credentials):
        self._creds = creds
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def get_profile(self) -> dict[str, Any]:
        return self._service.users().getProfile(userId="me").execute()

    def list_history(self, start_history_id: str, *, max_results: int = 50) -> dict[str, Any]:
        try:
            result = (
                self._service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=start_history_id,
                    historyTypes=["messageAdded"],
                    maxResults=max_results,
                )
                .execute()
            )
        except Exception as exc:
            raise exc
        message_ids: list[str] = []
        for entry in result.get("history") or []:
            for item in entry.get("messagesAdded") or []:
                msg = item.get("message") or {}
                mid = msg.get("id")
                if mid:
                    message_ids.append(str(mid))
        return {
            "history_id": str(result.get("historyId") or start_history_id),
            "message_ids": message_ids,
        }

    def list_messages(
        self,
        *,
        query: str = "",
        label_ids: list[str] | None = None,
        max_results: int = 10,
        page_token: str | None = None,
    ) -> tuple[list[str], str | None]:
        params: dict[str, Any] = {"userId": "me", "maxResults": max_results}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        if page_token:
            params["pageToken"] = page_token
        result = self._service.users().messages().list(**params).execute()
        items = result.get("messages") or []
        ids = [str(m["id"]) for m in items if isinstance(m, dict) and m.get("id")]
        return ids, result.get("nextPageToken")

    def iter_message_ids(
        self,
        *,
        query: str = "",
        max_results: int = 500,
        page_size: int = 100,
    ) -> list[str]:
        collected: list[str] = []
        page_token: str | None = None
        while len(collected) < max_results:
            batch_size = min(page_size, max_results - len(collected))
            ids, page_token = self.list_messages(
                query=query,
                max_results=batch_size,
                page_token=page_token,
            )
            collected.extend(ids)
            if not page_token or not ids:
                break
        return collected

    def get_message(self, message_id: str) -> GmailMessage:
        raw = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return _parse_message(raw)

    def get_message_metadata(self, message_id: str) -> GmailMessage:
        """Lightweight fetch for list/search UIs (Google samples metadata pattern)."""
        raw = (
            self._service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            )
            .execute()
        )
        return _parse_message(raw)

    def get_messages(self, message_ids: list[str]) -> list[GmailMessage]:
        return [self.get_message(mid) for mid in message_ids]

    def get_messages_metadata(self, message_ids: list[str]) -> list[GmailMessage]:
        return [self.get_message_metadata(mid) for mid in message_ids]

    def search_messages(self, query: str, *, max_results: int = 10) -> list[GmailMessage]:
        ids = self.list_messages(query=query, max_results=max_results)[0]
        return self.get_messages(ids)

    def search_message_previews(self, query: str, *, max_results: int = 10) -> list[GmailMessage]:
        """Search inbox using metadata-only fetches (faster for WhatsApp)."""
        ids = self.list_messages(query=query, max_results=max_results)[0]
        return self.get_messages_metadata(ids)

    def send_message(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        cc: str = "",
        bcc: str = "",
    ) -> dict[str, Any]:
        if html_body:
            msg: MIMEText | MIMEMultipart = MIMEMultipart("alternative")
            msg.attach(MIMEText(body or "Please view this message in HTML mode.", "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        else:
            msg = MIMEText(body, "plain", "utf-8")
        msg["to"] = to
        msg["subject"] = subject
        if cc:
            msg["cc"] = cc
        if bcc:
            msg["bcc"] = bcc
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        return (
            self._service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )

    def modify_labels(
        self,
        message_id: str,
        *,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels
        return (
            self._service.users()
            .messages()
            .modify(userId="me", id=message_id, body=body)
            .execute()
        )

    def trash_message(self, message_id: str) -> dict[str, Any]:
        return self._service.users().messages().trash(userId="me", id=message_id).execute()

    def delete_message(self, message_id: str) -> None:
        self._service.users().messages().delete(userId="me", id=message_id).execute()
