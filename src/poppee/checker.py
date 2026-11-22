"""Polls every account and decides what deserves a notification."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

from . import auth
from .config import DEFAULT_QUERY, Account, Config
from .gmail import AuthError, GmailClient, GmailError, Message, inbox_url
from .notify import Notification, Notifier
from .state import State

log = logging.getLogger(__name__)

RECENT_LIMIT = 10  # messages kept per account for the preview window
FETCH_LIMIT = 25  # new messages fetched per account per check
SEEN_LIMIT = 2000  # message ids remembered per account
MAX_WORKERS = 4
INBOX_RECENT_QUERY = "in:inbox"

ClientFactory = Callable[[Account], GmailClient]


def default_client_factory(account: Account) -> GmailClient:
    return GmailClient(auth.session_for(account.email))


@dataclass
class AccountResult:
    account: Account
    unread: int = 0
    more: bool = False
    new: list[Message] = field(default_factory=list)
    recent: list[Message] = field(default_factory=list)
    inbox_recent: list[Message] = field(default_factory=list)
    error: str | None = None

    @property
    def count_label(self) -> str:
        return f"{self.unread}+" if self.more else str(self.unread)


class Checker:
    def __init__(
        self,
        config: Config,
        state: State,
        notifier: Notifier,
        client_factory: ClientFactory | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.config = config
        self.state = state
        self.notifier = notifier
        self.client_factory = client_factory or default_client_factory
        self.clock = clock
        self.results: list[AccountResult] = []
        self._clients: dict[str, GmailClient] = {}
        self._lock = threading.Lock()

    def check_all(self, notify: bool = True) -> list[AccountResult]:
        with self._lock:
            accounts = [a for a in self.config.accounts if a.enabled]
            if accounts:
                with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(accounts))) as pool:
                    results = list(pool.map(self.check_account, accounts))
            else:
                results = []
            self.state.prune({a.key for a in self.config.accounts})
            self.state.save()
            if notify and self.config.notifications:
                self._notify(results)
            self.results = results
            return results

    def _client(self, account: Account) -> GmailClient:
        client = self._clients.get(account.key)
        if client is None:
            client = self._clients[account.key] = self.client_factory(account)
        return client

    def invalidate_client(self, account_email: str) -> None:
        """Drop a cached GmailClient so the next call loads fresh credentials."""
        with self._lock:
            self._clients.pop(account_email.lower(), None)

    def check_account(self, account: Account) -> AccountResult:
        result = AccountResult(account)
        st = self.state.account(account.email)
        st["name"] = account.name
        st["email"] = account.email
        try:
            client = self._client(account)
            ids, more = client.unread_ids(account.query)
            if account.query.strip().lower() == INBOX_RECENT_QUERY:
                inbox_ids = ids[:RECENT_LIMIT]
            else:
                try:
                    inbox_ids, _ = client.unread_ids(INBOX_RECENT_QUERY, limit=RECENT_LIMIT)
                except GmailError as e:
                    log.debug("%s: inbox recent lookup skipped: %s", account.email, e)
                    inbox_ids = ids[:RECENT_LIMIT]

            now = self.clock()
            if st.get("query") != account.query:
                # First check, or the search changed: treat what's there now as already seen.
                st["query"] = account.query
                st["baseline"] = 0.0 if self.config.notify_existing_on_start else now
                seen: set[str] = set() if self.config.notify_existing_on_start else set(ids)
            else:
                seen = set(st.get("seen", []))
            baseline = float(st.get("baseline", 0.0))

            cache: dict[str, Message] = {}
            for raw in st.get("inbox_recent", []):
                cache[raw["id"]] = Message.from_dict(raw)
            for raw in st.get("recent", []):
                cache[raw["id"]] = Message.from_dict(raw)

            unread_id_set = set(ids)
            candidates = [i for i in ids if i not in seen][:FETCH_LIMIT]
            to_fetch = dict.fromkeys(candidates + ids[:RECENT_LIMIT] + inbox_ids[:RECENT_LIMIT])
            for msg_id in to_fetch:
                if msg_id not in cache:
                    try:
                        cache[msg_id] = client.message(msg_id)
                    except AuthError:
                        raise
                    except GmailError as e:  # e.g. deleted between list and fetch
                        log.debug("%s: skipping message %s: %s", account.email, msg_id, e)

            # Keep unread flag accurate for inbox_recent independently of account filters.
            normalized_query = account.query.strip().lower()
            inbox_unread_set: set[str] | None
            if normalized_query == DEFAULT_QUERY:
                inbox_unread_set = unread_id_set
            else:
                try:
                    inbox_unread_ids, _ = client.unread_ids(DEFAULT_QUERY, limit=100)
                    inbox_unread_set = set(inbox_unread_ids)
                except GmailError as e:
                    log.debug("%s: inbox unread status lookup skipped: %s", account.email, e)
                    inbox_unread_set = None

            if inbox_unread_set is not None:
                for msg_id in inbox_ids[:RECENT_LIMIT]:
                    if msg_id in cache:
                        expected_unread = msg_id in inbox_unread_set
                        if cache[msg_id].unread != expected_unread:
                            cache[msg_id] = replace(cache[msg_id], unread=expected_unread)

            # Messages older than the baseline were already there before Poppee started
            # watching (e.g. old unread mail scrolling into the first page of results).
            result.new = [
                cache[i] for i in candidates if i in cache and cache[i].timestamp >= baseline
            ]
            result.recent = [cache[i] for i in ids[:RECENT_LIMIT] if i in cache]
            result.inbox_recent = [cache[i] for i in inbox_ids[:RECENT_LIMIT] if i in cache]
            result.unread, result.more = len(ids), more

            st["seen"] = list(dict.fromkeys(ids + st.get("seen", [])))[:SEEN_LIMIT]
            st.update(
                unread=result.unread,
                more=more,
                error=None,
                last_check=now,
                recent=[m.to_dict() for m in result.recent],
                inbox_recent=[m.to_dict() for m in result.inbox_recent],
            )
        except AuthError as e:
            self._clients.pop(account.key, None)
            result.error = f"Sign-in needed: {e}"
        except GmailError as e:
            result.error = str(e)
        except Exception as e:  # never let one account break the loop
            log.exception("Unexpected error checking %s", account.email)
            self._clients.pop(account.key, None)
            result.error = f"{type(e).__name__}: {e}"

        if result.error:
            log.warning("%s: %s", account.email, result.error)
            st["error"] = result.error
            st["last_check"] = self.clock()
            result.unread, result.more = st.get("unread", 0), st.get("more", False)
            result.recent = [Message.from_dict(m) for m in st.get("recent", [])]
            result.inbox_recent = [Message.from_dict(m) for m in st.get("inbox_recent", [])]
        return result

    def mark_as_read(self, account_email: str, message_id: str) -> list[AccountResult]:
        """Mark a message as read in Gmail and update local results + state."""
        with self._lock:
            account = self.config.find_account(account_email)
            if account is None:
                raise GmailError(f"Unknown account: {account_email}")
            client = self._client(account)
            try:
                client.mark_as_read(message_id)
            except AuthError:
                self._clients.pop(account.key, None)
                raise

            updated: list[AccountResult] = []
            for res in self.results:
                if res.account.key != account.key:
                    updated.append(res)
                    continue
                was_in_recent = any(m.id == message_id for m in res.recent)
                new_recent = [m for m in res.recent if m.id != message_id]
                new_inbox_recent = [
                    replace(m, unread=False) if m.id == message_id else m for m in res.inbox_recent
                ]
                new_unread = max(0, res.unread - (1 if was_in_recent else 0))
                new_res = replace(
                    res,
                    unread=new_unread,
                    recent=new_recent,
                    inbox_recent=new_inbox_recent,
                )
                updated.append(new_res)

                st = self.state.account(account.email)
                st["unread"] = new_unread
                st["recent"] = [m.to_dict() for m in new_recent]
                st["inbox_recent"] = [m.to_dict() for m in new_inbox_recent]

            self.results = updated
            self.state.save()
            return list(self.results)

    def _notify(self, results: list[AccountResult]) -> None:
        for result in results:
            if result.account.notify and result.new:
                for n in build_notifications(result, self.config.max_notifications):
                    self.notifier.send(n)


def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_notifications(result: AccountResult, max_individual: int) -> list[Notification]:
    account = result.account
    new = sorted(result.new, key=lambda m: m.timestamp)
    if len(new) <= max_individual:
        return [
            Notification(
                title=_trim(f"{m.sender} · {account.name}", 80),
                body=_trim(f"{m.subject}\n{m.snippet}".strip(), 240),
                url=m.url(account.email),
            )
            for m in new
        ]
    shown = new[-5:][::-1]  # newest first
    lines = [_trim(f"{m.sender}: {m.subject}", 80) for m in shown]
    if len(new) > len(shown):
        lines.append(f"…and {len(new) - len(shown)} more")
    return [
        Notification(
            title=f"{len(new)} new messages · {account.name}",
            body="\n".join(lines),
            url=inbox_url(account.email),
        )
    ]
