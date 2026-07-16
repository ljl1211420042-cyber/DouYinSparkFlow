import json
import os
import re
import tempfile
from pathlib import Path


COOKIE_FIELDS = {
    "domain",
    "expires",
    "httpOnly",
    "name",
    "path",
    "sameSite",
    "secure",
    "value",
}
REQUIRED_COOKIE_FIELDS = {"domain", "name", "path", "value"}
COOKIE_KEY_PATTERN = re.compile(r"^COOKIES_[A-Z0-9_]+$")


def cookie_key(unique_id) -> str:
    value = str(unique_id or "").strip()
    if not value:
        raise ValueError("Cookie state unique_id must not be empty")
    return f"COOKIES_{value}".upper()


def normalize_cookies(cookies) -> list[dict]:
    if not isinstance(cookies, list):
        raise ValueError("Cookie state value must be a list")

    normalized = []
    for index, cookie in enumerate(cookies):
        if not isinstance(cookie, dict):
            raise ValueError(f"Cookie at index {index} must be an object")

        missing = REQUIRED_COOKIE_FIELDS.difference(cookie)
        if missing:
            fields = ", ".join(sorted(missing))
            raise ValueError(
                f"Cookie at index {index} is missing required fields: {fields}"
            )

        normalized.append(
            {key: cookie[key] for key in COOKIE_FIELDS if key in cookie}
        )

    return normalized


def validate_cookie_state(state) -> dict[str, list[dict]]:
    if not isinstance(state, dict):
        raise ValueError("Cookie state must be a JSON object")

    normalized = {}
    for key, cookies in state.items():
        if not isinstance(key, str) or not COOKIE_KEY_PATTERN.fullmatch(key):
            raise ValueError("Cookie state keys must match COOKIES_<unique_id>")
        normalized[key] = normalize_cookies(cookies)
    return normalized


def load_cookie_state(path) -> dict[str, list[dict]]:
    if not path:
        return {}
    with open(path, encoding="utf-8") as state_file:
        return validate_cookie_state(json.load(state_file))


def write_cookie_state(path, state) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized = validate_cookie_state(state)

    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    try:
        os.chmod(temporary_path, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as state_file:
            json.dump(normalized, state_file, ensure_ascii=False, separators=(",", ":"))
            state_file.flush()
            os.fsync(state_file.fileno())
        os.replace(temporary_path, destination)
        os.chmod(destination, 0o600)
    except Exception:
        try:
            os.close(file_descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise
