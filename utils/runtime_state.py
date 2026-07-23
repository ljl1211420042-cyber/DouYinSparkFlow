import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

from utils.cookie_state import (
    cookie_key,
    normalize_cookies,
    validate_cookie_state,
)


VERSION = 1
TOP_LEVEL_FIELDS = {"version", "accounts", "ledger"}
TARGET_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LEDGER_ENTRY_FIELDS = {"status", "sent_at"}


def target_hash(target) -> str:
    value = str(target or "").strip()
    if not value:
        raise ValueError("Target ID must not be empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_runtime_state(accounts=None) -> dict:
    return {
        "version": VERSION,
        "accounts": validate_cookie_state(accounts or {}),
        "ledger": {},
    }


def validate_runtime_state(state) -> dict:
    if not isinstance(state, dict):
        raise ValueError("Runtime state must be a JSON object")
    if set(state) != TOP_LEVEL_FIELDS:
        raise ValueError("Runtime state has invalid top-level fields")
    if state["version"] != VERSION:
        raise ValueError("Unsupported runtime-state version")
    normalized = new_runtime_state(state["accounts"])
    if not isinstance(state["ledger"], dict):
        raise ValueError("Runtime-state ledger must be an object")
    for day_text, entries in state["ledger"].items():
        date.fromisoformat(day_text)
        if not isinstance(entries, dict):
            raise ValueError("Daily ledger must be an object")
        normalized["ledger"][day_text] = {}
        for digest, entry in entries.items():
            if not TARGET_HASH_PATTERN.fullmatch(digest):
                raise ValueError("Invalid target hash")
            if not isinstance(entry, dict) or set(entry) != LEDGER_ENTRY_FIELDS:
                raise ValueError("Invalid ledger entry")
            if entry["status"] != "sent":
                raise ValueError("Invalid ledger status")
            datetime.fromisoformat(entry["sent_at"])
            normalized["ledger"][day_text][digest] = dict(entry)
    return normalized


def load_runtime_state(path) -> dict:
    if not path:
        return new_runtime_state()
    with open(path, encoding="utf-8") as state_file:
        return validate_runtime_state(json.load(state_file))


def write_runtime_state(path, state) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized = validate_runtime_state(state)
    descriptor, temporary_path = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    try:
        os.chmod(temporary_path, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as state_file:
            json.dump(
                normalized,
                state_file,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            state_file.flush()
            os.fsync(state_file.fileno())
        os.replace(temporary_path, destination)
        os.chmod(destination, 0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def set_account_cookies(state, unique_id, cookies) -> None:
    state["accounts"][cookie_key(unique_id)] = normalize_cookies(cookies)


def was_sent(state, target, day: date) -> bool:
    return target_hash(target) in state["ledger"].get(day.isoformat(), {})


def mark_sent(state, target, sent_at: datetime) -> None:
    day_entries = state["ledger"].setdefault(
        sent_at.date().isoformat(),
        {},
    )
    day_entries[target_hash(target)] = {
        "status": "sent",
        "sent_at": sent_at.isoformat(),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices={"validate"})
    parser.add_argument("path")
    args = parser.parse_args()
    load_runtime_state(args.path)


if __name__ == "__main__":
    main()
