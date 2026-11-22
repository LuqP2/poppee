"""Persistent per-account and UI state shared by the checker, widget and CLI."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


class State:
    """Thread-safe JSON state store with atomic writes."""

    def __init__(self, path: Path, readonly: bool = False):
        self.path = path
        self.readonly = readonly
        self._lock = threading.RLock()
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("accounts"), dict):
                if not isinstance(data.get("ui"), dict):
                    data["ui"] = {}
                return data
        except (OSError, ValueError):
            pass
        return {"version": 1, "accounts": {}, "ui": {}}

    def account(self, email: str) -> dict[str, Any]:
        with self._lock:
            return self.data["accounts"].setdefault(email.lower(), {})

    def get_ui(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return copy.deepcopy(self.data.setdefault("ui", {}).get(key, default))

    def set_ui(self, key: str, value: Any, *, save: bool = True) -> None:
        with self._lock:
            self.data.setdefault("ui", {})[key] = copy.deepcopy(value)
            if save:
                self.save()

    def prune(self, keep: set[str]) -> None:
        with self._lock:
            for key in list(self.data["accounts"]):
                if key not in keep:
                    del self.data["accounts"][key]

    def save(self) -> None:
        if self.readonly:
            return
        with self._lock:
            payload = json.dumps(self.data, indent=1, ensure_ascii=False)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
            )
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                # Retry briefly on Windows if another reader holds a transient handle.
                for attempt in range(4):
                    try:
                        os.replace(tmp, self.path)
                        break
                    except PermissionError:
                        if attempt == 3:
                            raise
                        time.sleep(0.02 * (attempt + 1))
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
