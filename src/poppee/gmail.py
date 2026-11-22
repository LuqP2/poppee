"""Minimal Gmail REST API client (just what a notifier/widget needs)."""

from __future__ import annotations

import base64
import html
from dataclasses import asdict, dataclass
from email.utils import parseaddr
from typing import Protocol
from urllib.parse import quote

import requests
from google.auth.exceptions import RefreshError, TransportError

API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailError(Exception):
    """A request to Gmail failed."""


class AuthError(GmailError):
    """The account needs to be signed in again."""


class Session(Protocol):
    def get(self, url: str, params=None, timeout: float | None = None): ...
    def post(self, url: str, json=None, timeout: float | None = None): ...


def inbox_url(email: str) -> str:
    return f"https://mail.google.com/mail/?authuser={quote(email)}#inbox"


@dataclass(frozen=True)
class Message:
    id: str
    thread_id: str
    sender: str
    sender_email: str
    subject: str
    snippet: str
    timestamp: float  # seconds since the epoch, when Gmail received it
    unread: bool = True

    def url(self, account_email: str) -> str:
        return f"https://mail.google.com/mail/?authuser={quote(account_email)}#all/{self.thread_id}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Message:
        kwargs = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**kwargs)


@dataclass(frozen=True)
class MessageBody:
    id: str
    text: str = ""
    html: str = ""


def _decode_base64url(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_mime_body(payload: dict) -> tuple[str, str]:
    """Recursively extract (plain_text, html_text) from a Gmail MIME payload."""
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def _walk(node: dict) -> None:
        mime = str(node.get("mimeType", "")).lower()
        body_data = node.get("body", {}).get("data", "")
        if body_data:
            decoded = _decode_base64url(body_data)
            if mime == "text/plain":
                plain_parts.append(decoded)
            elif mime == "text/html":
                html_parts.append(decoded)
            elif not node.get("parts"):
                plain_parts.append(decoded)
        for child in node.get("parts") or []:
            if isinstance(child, dict):
                _walk(child)

    _walk(payload)
    return "\n".join(p for p in plain_parts if p).strip(), "\n".join(
        h for h in html_parts if h
    ).strip()


class GmailClient:
    def __init__(self, session: Session, timeout: float = 30):
        self.session = session
        self.timeout = timeout

    def _handle_response(self, resp, *, permission_hint: str | None = None) -> dict:
        if resp.status_code >= 400:
            try:
                detail = resp.json()["error"]["message"]
            except Exception:
                detail = resp.text[:200] if hasattr(resp, "text") else ""
            if resp.status_code == 401:
                raise AuthError(f"sign-in rejected: {detail}")
            if resp.status_code == 403 and permission_hint:
                raise AuthError(f"{permission_hint}: {detail}")
            raise GmailError(f"HTTP {resp.status_code}: {detail}")
        return resp.json()

    def _get(self, path: str, params=None) -> dict:
        try:
            resp = self.session.get(API_ROOT + path, params=params, timeout=self.timeout)
        except RefreshError as e:
            raise AuthError(f"sign-in expired or revoked ({e}) - run `poppee add-account`") from e
        except (requests.RequestException, TransportError) as e:
            raise GmailError(f"network error: {e}") from e
        return self._handle_response(resp)

    def _post(self, path: str, body: dict, *, permission_hint: str | None = None) -> dict:
        try:
            resp = self.session.post(API_ROOT + path, json=body, timeout=self.timeout)
        except RefreshError as e:
            raise AuthError(f"sign-in expired or revoked ({e}) - run `poppee add-account`") from e
        except (requests.RequestException, TransportError) as e:
            raise GmailError(f"network error: {e}") from e
        return self._handle_response(resp, permission_hint=permission_hint)

    def email_address(self) -> str:
        return self._get("/profile")["emailAddress"]

    def unread_ids(self, query: str, limit: int = 100) -> tuple[list[str], bool]:
        """Return up to ``limit`` matching message ids (newest first) and whether there are more."""
        data = self._get("/messages", {"q": query, "maxResults": limit})
        ids = [m["id"] for m in data.get("messages", [])]
        return ids, bool(data.get("nextPageToken"))

    def message(self, msg_id: str) -> Message:
        data = self._get(
            f"/messages/{msg_id}",
            [("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject")],
        )
        headers = {
            h.get("name", "").lower(): h.get("value", "")
            for h in data.get("payload", {}).get("headers", [])
        }
        name, address = parseaddr(headers.get("from", ""))
        label_ids = data.get("labelIds")
        is_unread = "UNREAD" in label_ids if isinstance(label_ids, list) else True
        return Message(
            id=data["id"],
            thread_id=data.get("threadId", data["id"]),
            sender=name or address or "(unknown sender)",
            sender_email=address,
            subject=headers.get("subject", "").strip() or "(no subject)",
            snippet=html.unescape(data.get("snippet", "")).strip(),
            timestamp=int(data.get("internalDate", 0)) / 1000,
            unread=is_unread,
        )

    def message_body(self, msg_id: str) -> MessageBody:
        """Fetch full MIME message and return decoded plain text and HTML bodies."""
        data = self._get(f"/messages/{msg_id}", [("format", "full")])
        text, html_body = _extract_mime_body(data.get("payload", {}))
        if not text and not html_body:
            text = html.unescape(data.get("snippet", "")).strip()
        return MessageBody(id=data.get("id", msg_id), text=text, html=html_body)

    def mark_as_read(self, msg_id: str) -> None:
        """Remove the UNREAD label from ``msg_id``."""
        self._post(
            f"/messages/{msg_id}/modify",
            {"removeLabelIds": ["UNREAD"]},
            permission_hint="missing gmail.modify permission - run `poppee add-account`",
        )
