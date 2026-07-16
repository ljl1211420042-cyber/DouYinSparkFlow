import json
import os
import sys

from utils.cookie_state import load_cookie_state, validate_cookie_state


RESERVED_SECRETS = {"COOKIE_STATE_KEY"}


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def to_dotenv_value(value: str) -> str:
    # Keep .env single-line values by escaping real line breaks.
    return value.replace("\r", "").replace("\n", "\\n")


def append_github_env_block(env_file, key: str, value: str) -> None:
    env_file.write(f"{key}<<__ENV_EOF__\n")
    env_file.write(value)
    env_file.write("\n__ENV_EOF__\n")


def as_env_string(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def format_key_list(keys) -> str:
    if not keys:
        return "(none)"
    return ", ".join(sorted(str(key) for key in keys))


def build_environment(vars_map, secrets_map, cookie_state) -> dict[str, str]:
    environment = {
        str(key): as_env_string(value) for key, value in vars_map.items()
    }
    environment.update(
        {
            str(key): as_env_string(value)
            for key, value in secrets_map.items()
            if str(key) not in RESERVED_SECRETS
        }
    )
    environment.update(
        {
            key: as_env_string(value)
            for key, value in validate_cookie_state(cookie_state).items()
        }
    )
    return environment


def main() -> None:
    vars_raw = os.getenv("VARS_JSON", "{}")
    secrets_raw = os.getenv("SECRETS_JSON", "{}")
    github_env = os.getenv("GITHUB_ENV")
    cookie_state_file = os.getenv("COOKIE_STATE_FILE", "")

    if not github_env:
        fail("GITHUB_ENV is not set")

    try:
        vars_map = json.loads(vars_raw)
    except json.JSONDecodeError as exc:
        fail(f"VARS_JSON is not valid JSON: {exc}")

    try:
        secrets_map = json.loads(secrets_raw)
    except json.JSONDecodeError as exc:
        fail(f"SECRETS_JSON is not valid JSON: {exc}")

    if not isinstance(vars_map, dict):
        fail("VARS_JSON must be a JSON object")
    if not isinstance(secrets_map, dict):
        fail("SECRETS_JSON must be a JSON object")

    vars_keys = list(vars_map.keys())
    secrets_keys = list(secrets_map.keys())
    cookie_state = load_cookie_state(cookie_state_file)
    dotenv_map = build_environment(vars_map, secrets_map, cookie_state)

    with open(github_env, "a", encoding="utf-8") as env_file:
        for key, value in dotenv_map.items():
            append_github_env_block(env_file, key, value)

    dotenv_lines = [f"{key}={to_dotenv_value(value)}" for key, value in dotenv_map.items()]
    with open(".env", "w", encoding="utf-8") as dotenv_file:
        dotenv_file.write("\n".join(dotenv_lines) + "\n")

    print(
        "Exported all variables from VARS_JSON and SECRETS_JSON; .env refreshed."
    )
    print(f"VARS_JSON exported ({len(vars_keys)}): {format_key_list(vars_keys)}")
    print(
        "SECRETS_JSON exported "
        f"({len(secrets_keys)}): {format_key_list(secrets_keys)}"
    )
    print(f"Refreshed cookie states loaded: {len(cookie_state)}")


if __name__ == "__main__":
    main()
