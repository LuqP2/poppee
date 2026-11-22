"""Loading, validating and editing ``config.toml``."""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

DEFAULT_QUERY = "is:unread in:inbox"
MIN_POLL_INTERVAL = 30

TEMPLATE = """\
# Poppee configuration.
# After editing, choose "Reload config" from the tray menu or restart Poppee.

# How often to check each account, in seconds (minimum 30).
poll_interval = 120

# Show desktop notifications for new mail (off by default; the floating widget shows unread mail).
notifications = false

# If more than this many new messages arrive for one account in a single
# check, show one summary notification instead of one per message.
max_notifications = 3

# Also notify about mail that is already unread the first time an account is checked.
notify_existing_on_start = false

# Clicking a notification opens the message in Gmail (where the desktop supports it).
click_to_open = true

# OAuth client file downloaded from Google Cloud Console ("Desktop app" client).
# Relative paths are resolved against the directory this file is in.
client_secret_file = "client_secret.json"

# Accounts are added by `poppee add-account`, or you can write them by hand:
#
# [[accounts]]
# name = "Forum alerts"           # label shown in notifications and the tray menu
# email = "someone@gmail.com"
# query = "is:unread in:inbox"    # any Gmail search, e.g. "is:unread label:forums"
# notify = true                   # false = count in the tray only, no pop-ups
# enabled = true                  # false = don't check this account at all
"""

_TOP_LEVEL_KEYS = {
    "poll_interval",
    "notifications",
    "max_notifications",
    "notify_existing_on_start",
    "click_to_open",
    "client_secret_file",
    "accounts",
}
_ACCOUNT_KEYS = {"name", "email", "query", "notify", "enabled"}


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class Account:
    email: str
    name: str
    query: str = DEFAULT_QUERY
    notify: bool = True
    enabled: bool = True

    @property
    def key(self) -> str:
        return self.email.lower()


@dataclass(frozen=True)
class Config:
    client_secret_file: Path
    accounts: list[Account] = field(default_factory=list)
    poll_interval: int = 120
    notifications: bool = False
    max_notifications: int = 3
    notify_existing_on_start: bool = False
    click_to_open: bool = True
    path: Path | None = None

    def find_account(self, email: str) -> Account | None:
        return next((a for a in self.accounts if a.key == email.lower()), None)


def load(path: Path | None = None) -> Config:
    path = path or paths.config_file()
    if not path.exists():
        raise ConfigError(f"No config file at {path}. Run `poppee init` first.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    return parse(data, base_dir=path.parent, path=path)


def parse(data: dict, base_dir: Path, path: Path | None = None) -> Config:
    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(f"Unknown setting(s): {', '.join(sorted(unknown))}")

    client_secret = Path(_get(data, "client_secret_file", str, "client_secret.json")).expanduser()
    if not client_secret.is_absolute():
        client_secret = base_dir / client_secret

    poll_interval = _get(data, "poll_interval", int, 120)
    if poll_interval < MIN_POLL_INTERVAL:
        raise ConfigError(f"poll_interval must be at least {MIN_POLL_INTERVAL} seconds")
    max_notifications = _get(data, "max_notifications", int, 3)
    if max_notifications < 0:
        raise ConfigError("max_notifications must not be negative")

    return Config(
        client_secret_file=client_secret,
        accounts=_parse_accounts(data.get("accounts", [])),
        poll_interval=poll_interval,
        notifications=_get(data, "notifications", bool, False),
        max_notifications=max_notifications,
        notify_existing_on_start=_get(data, "notify_existing_on_start", bool, False),
        click_to_open=_get(data, "click_to_open", bool, True),
        path=path,
    )


def _parse_accounts(raw: object) -> list[Account]:
    if not isinstance(raw, list):
        raise ConfigError("`accounts` must be a list of [[accounts]] tables")
    accounts: list[Account] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw, 1):
        where = f"account #{i}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be a table")
        unknown = set(entry) - _ACCOUNT_KEYS
        if unknown:
            raise ConfigError(f"{where}: unknown setting(s): {', '.join(sorted(unknown))}")
        email = entry.get("email")
        if not isinstance(email, str) or "@" not in email:
            raise ConfigError(f"{where}: `email` must be an email address")
        email = email.strip()
        where = f"account {email}"
        if email.lower() in seen:
            raise ConfigError(f"{where} is listed more than once")
        seen.add(email.lower())
        query = _get(entry, "query", str, DEFAULT_QUERY, where).strip()
        if not query:
            raise ConfigError(f"{where}: `query` must not be empty")
        accounts.append(
            Account(
                email=email,
                name=_get(entry, "name", str, "", where).strip() or email,
                query=query,
                notify=_get(entry, "notify", bool, True, where),
                enabled=_get(entry, "enabled", bool, True, where),
            )
        )
    return accounts


def _get(data: dict, key: str, typ: type, default, where: str = ""):
    value = data.get(key, default)
    # bool is a subclass of int; don't accept `true` where a number is expected.
    if not isinstance(value, typ) or (typ is int and isinstance(value, bool)):
        prefix = f"{where}: " if where else ""
        raise ConfigError(f"{prefix}`{key}` must be of type {typ.__name__}")
    return value


def write_template(path: Path) -> bool:
    """Create a commented default config. Returns False if one already exists."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    return True


def _toml_str(value: str) -> str:
    # JSON string escapes are a subset of TOML basic-string escapes.
    return json.dumps(value, ensure_ascii=False)


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def save(path: Path, cfg: Config) -> None:
    """Serialize ``cfg`` to ``path`` atomically as clean, readable TOML."""
    try:
        rel_secret = cfg.client_secret_file.relative_to(path.parent)
        secret_str = str(rel_secret)
    except ValueError:
        secret_str = str(cfg.client_secret_file)

    lines = [
        "# Poppee configuration.",
        "",
        f"poll_interval = {max(MIN_POLL_INTERVAL, int(cfg.poll_interval))}",
        f"notifications = {_toml_bool(cfg.notifications)}",
        f"max_notifications = {max(0, int(cfg.max_notifications))}",
        f"notify_existing_on_start = {_toml_bool(cfg.notify_existing_on_start)}",
        f"click_to_open = {_toml_bool(cfg.click_to_open)}",
        f"client_secret_file = {_toml_str(secret_str)}",
    ]

    for acc in cfg.accounts:
        lines.extend(
            [
                "",
                "[[accounts]]",
                f"name = {_toml_str(acc.name)}",
                f"email = {_toml_str(acc.email)}",
                f"query = {_toml_str(acc.query)}",
                f"notify = {_toml_bool(acc.notify)}",
                f"enabled = {_toml_bool(acc.enabled)}",
            ]
        )

    payload = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def append_account(path: Path, email: str, name: str | None = None, query: str | None = None):
    lines = [
        "",
        "[[accounts]]",
        f"name = {_toml_str(name or email)}",
        f"email = {_toml_str(email)}",
    ]
    if query and query != DEFAULT_QUERY:
        lines.append(f"query = {_toml_str(query)}")
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")


_TABLE_HEADER = re.compile(r"^\s*\[")
_ACCOUNT_HEADER = re.compile(r"^\s*\[\[\s*accounts\s*\]\]\s*(#.*)?$")


def remove_account(path: Path, email: str) -> bool:
    """Remove the ``[[accounts]]`` block for ``email``, keeping the rest of the file intact."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    i = 0
    while i < len(lines):
        if not _ACCOUNT_HEADER.match(lines[i]):
            i += 1
            continue
        end = i + 1
        while end < len(lines) and not _TABLE_HEADER.match(lines[end]):
            end += 1
        try:
            block = tomllib.loads("".join(lines[i + 1 : end]))
        except tomllib.TOMLDecodeError:
            block = {}
        if str(block.get("email", "")).lower() == email.lower():
            del lines[i:end]
            path.write_text("".join(lines), encoding="utf-8")
            return True
        i = end
    return False
