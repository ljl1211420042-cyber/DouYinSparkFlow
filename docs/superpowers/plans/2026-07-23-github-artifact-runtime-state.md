# GitHub Artifact Runtime State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Douyin streak task on GitHub-hosted runners with encrypted cross-run cookies, an at-most-once daily send ledger, and a one-time local QR login bootstrap.

**Architecture:** A versioned runtime-state module stores normalized Playwright cookies and a hashed daily send ledger. GitHub Actions restores the newest encrypted state artifact and refuses to send if it detects a run without a successor state artifact; the task writes state after every verified send, and a local visible-browser command securely bootstraps GitHub Environment Secrets.

**Tech Stack:** Python 3.11, Playwright 1.58, `unittest`, GitHub Actions, GitHub CLI, OpenSSL AES-256-CBC with PBKDF2, encrypted workflow artifacts.

---

## File Map

- Create `utils/runtime_state.py`: versioned cookies-plus-ledger validation,
  target hashing, atomic state writes, and CLI validation.
- Create `utils/artifact_state.py`: choose and download the newest encrypted
  runtime artifact and fail closed when workflow-state continuity is broken.
- Modify `utils/export_github_env.py`: overlay cookies from a validated runtime
  state while retaining bootstrap Secret fallback.
- Modify `core/tasks.py`: carry exact target IDs through selection, skip targets
  already sent today, verify a single new message, and persist state after each
  verified send.
- Modify `utils/config.py`: parse the runtime-state paths and the
  `Asia/Shanghai` ledger date.
- Create `scripts/bootstrap_github_login.py`: visible QR login, creator-chat
  validation, and secret upload over subprocess standard input.
- Modify `.github/workflows/schedule.yml`: concurrency, artifact restore,
  fail-closed decryption, always-run state encryption/upload, cleanup, and
  validation-only bootstrap input.
- Create `tests/test_runtime_state.py`: state format and ledger tests.
- Create `tests/test_artifact_state.py`: newest artifact and continuity tests.
- Modify `tests/test_export_github_env.py`: runtime-state cookie precedence.
- Modify `tests/test_tasks.py`: skip, exact-send verification, and persistence
  tests.
- Create `tests/test_bootstrap_github_login.py`: secret transport and
  redaction tests.
- Modify `tests/test_workflow_cookie_state.py`: artifact workflow structure.

### Task 1: Preserve the Existing Conversation Guard and Reconcile the Branch

**Files:**
- Modify: `core/tasks.py`
- Modify: `tests/test_tasks.py`
- Preserve without staging: `tests/__init__.py`

- [ ] **Step 1: Verify the existing conversation-title regression tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_tasks.ConversationSelectionTests -v
```

Expected: two tests pass, including rejection of `咸鱼.` when `Bruno` is
expected.

- [ ] **Step 2: Verify the complete current suite**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected: 34 tests pass and `git diff --check` prints nothing.

- [ ] **Step 3: Commit only the conversation guard**

Run:

```bash
git add core/tasks.py tests/test_tasks.py
git commit -m "fix(chat): verify selected conversation"
```

Expected: the untracked `tests/__init__.py` is not included.

- [ ] **Step 4: Reconcile the feature branch with remote main**

Run:

```bash
git fetch origin
git merge --no-edit origin/main
```

Expected: the branch contains `origin/main`, the approved design commit, and
the conversation-guard commit. If Git reports a conflict, stop and resolve
only overlapping lines; do not discard either side with checkout/reset.

### Task 2: Add the Versioned Runtime-State Format

**Files:**
- Create: `utils/runtime_state.py`
- Create: `tests/test_runtime_state.py`

- [ ] **Step 1: Write failing state and ledger tests**

Create `tests/test_runtime_state.py` with:

```python
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from utils.runtime_state import (
    load_runtime_state,
    mark_sent,
    new_runtime_state,
    set_account_cookies,
    target_hash,
    was_sent,
    write_runtime_state,
)


COOKIE = {
    "name": "sessionid",
    "value": "secret",
    "domain": ".douyin.com",
    "path": "/",
}


class RuntimeStateTests(unittest.TestCase):
    def test_hashes_normalized_target_without_storing_raw_id(self):
        digest = target_hash(" 11x_y ")
        self.assertEqual(len(digest), 64)
        self.assertNotIn("11x_y", digest)

    def test_marks_and_checks_daily_send(self):
        state = new_runtime_state()
        sent_at = datetime.fromisoformat("2026-07-23T06:02:11+08:00")
        mark_sent(state, "11x_y", sent_at)
        self.assertTrue(was_sent(state, "11x_y", sent_at.date()))
        self.assertFalse(
            was_sent(
                state,
                "11x_y",
                datetime.fromisoformat("2026-07-24T06:02:11+08:00").date(),
            )
        )
        self.assertNotIn("11x_y", json.dumps(state))

    def test_round_trips_accounts_and_ledger_with_mode_0600(self):
        state = new_runtime_state()
        set_account_cookies(state, "90530392137", [COOKIE])
        mark_sent(
            state,
            "11x_y",
            datetime.fromisoformat("2026-07-23T06:02:11+08:00"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nested" / "runtime.json"
            write_runtime_state(path, state)
            self.assertEqual(load_runtime_state(path), state)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_rejects_unknown_top_level_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime.json"
            path.write_text(
                '{"version":1,"accounts":{},"ledger":{},"extra":true}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "top-level"):
                load_runtime_state(path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and observe the expected RED state**

Run:

```bash
.venv/bin/python -m unittest tests.test_runtime_state -v
```

Expected: import failure because `utils.runtime_state` does not exist.

- [ ] **Step 3: Implement the minimal runtime-state module**

Create `utils/runtime_state.py`:

```python
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
```

- [ ] **Step 4: Run focused and full tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_runtime_state -v
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the runtime-state unit**

Run:

```bash
git add utils/runtime_state.py tests/test_runtime_state.py
git commit -m "feat(state): add versioned runtime ledger"
```

### Task 3: Restore the Newest Artifact and Detect State Gaps

**Files:**
- Create: `utils/artifact_state.py`
- Create: `tests/test_artifact_state.py`

- [ ] **Step 1: Write failing artifact-selection tests**

Create `tests/test_artifact_state.py`:

```python
import unittest

from utils.artifact_state import (
    StateContinuityError,
    select_runtime_artifact,
)


class ArtifactStateTests(unittest.TestCase):
    def test_selects_newest_unexpired_runtime_artifact(self):
        artifacts = [
            {
                "id": 10,
                "name": "douyin-runtime-state-100",
                "expired": False,
                "created_at": "2026-07-22T00:00:00Z",
            },
            {
                "id": 11,
                "name": "douyin-runtime-state-101",
                "expired": False,
                "created_at": "2026-07-23T00:00:00Z",
            },
        ]
        artifact = select_runtime_artifact(
            artifacts,
            workflow_runs=[],
            current_run_id=102,
            allow_bootstrap=False,
        )
        self.assertEqual(artifact["id"], 11)

    def test_rejects_completed_run_newer_than_latest_state(self):
        artifacts = [
            {
                "id": 11,
                "name": "douyin-runtime-state-101",
                "expired": False,
                "created_at": "2026-07-23T00:00:00Z",
            }
        ]
        runs = [
            {
                "id": 102,
                "status": "completed",
                "event": "schedule",
                "conclusion": "cancelled",
            }
        ]
        with self.assertRaises(StateContinuityError):
            select_runtime_artifact(
                artifacts,
                workflow_runs=runs,
                current_run_id=103,
                allow_bootstrap=False,
            )

    def test_allows_explicit_first_bootstrap_without_artifact(self):
        self.assertIsNone(
            select_runtime_artifact(
                [],
                workflow_runs=[{"id": 90, "status": "completed"}],
                current_run_id=100,
                allow_bootstrap=True,
            )
        )

    def test_explicit_bootstrap_ignores_old_encrypted_artifact(self):
        self.assertIsNone(
            select_runtime_artifact(
                [
                    {
                        "id": 11,
                        "name": "douyin-runtime-state-101",
                        "expired": False,
                        "created_at": "2026-07-23T00:00:00Z",
                    }
                ],
                workflow_runs=[],
                current_run_id=102,
                allow_bootstrap=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_artifact_state -v
```

Expected: import failure because `utils.artifact_state` does not exist.

- [ ] **Step 3: Implement selection, continuity, and restore CLI**

Create `utils/artifact_state.py` with these public behaviors:

```python
import argparse
import json
import os
import subprocess
from pathlib import Path


PREFIX = "douyin-runtime-state-"


class StateContinuityError(RuntimeError):
    pass


def artifact_run_id(artifact):
    name = artifact.get("name", "")
    suffix = name.removeprefix(PREFIX)
    if not suffix.isdigit():
        raise ValueError("Invalid runtime-state artifact name")
    return int(suffix)


def select_runtime_artifact(
    artifacts,
    workflow_runs,
    current_run_id,
    allow_bootstrap,
):
    if allow_bootstrap:
        return None
    candidates = [
        artifact
        for artifact in artifacts
        if artifact.get("name", "").startswith(PREFIX)
        and not artifact.get("expired", False)
        and artifact_run_id(artifact) < current_run_id
    ]
    if not candidates:
        raise StateContinuityError(
            "No encrypted runtime-state artifact; run validation bootstrap"
        )
    latest = max(candidates, key=lambda item: item["created_at"])
    latest_run_id = artifact_run_id(latest)
    gaps = [
        run
        for run in workflow_runs
        if latest_run_id < run.get("id", 0) < current_run_id
        and run.get("status") == "completed"
        and run.get("event") in {"schedule", "workflow_dispatch"}
    ]
    if gaps:
        raise StateContinuityError(
            "A newer workflow run has no runtime-state artifact"
        )
    return latest


def gh_json(endpoint):
    completed = subprocess.run(
        ["gh", "api", endpoint],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def restore(repository, workflow_id, current_run_id, output, allow_bootstrap):
    artifacts_response = gh_json(
        f"repos/{repository}/actions/artifacts?per_page=100"
    )
    runs_response = gh_json(
        f"repos/{repository}/actions/workflows/{workflow_id}/runs?per_page=100"
    )
    artifact = select_runtime_artifact(
        artifacts_response.get("artifacts", []),
        runs_response.get("workflow_runs", []),
        current_run_id,
        allow_bootstrap,
    )
    if artifact is None:
        return False
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gh",
            "run",
            "download",
            str(artifact_run_id(artifact)),
            "--repo",
            repository,
            "--name",
            artifact["name"],
            "--dir",
            str(destination.parent),
        ],
        check=True,
    )
    downloaded = destination.parent / "state.enc"
    if downloaded != destination:
        downloaded.replace(destination)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices={"restore"})
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-bootstrap", action="store_true")
    args = parser.parse_args()
    restored = restore(
        args.repository,
        args.workflow,
        args.run_id,
        args.output,
        args.allow_bootstrap,
    )
    if restored:
        print("Encrypted runtime state restored")
    else:
        print("Runtime-state bootstrap requested")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify focused and full tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_artifact_state -v
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the artifact selector**

Run:

```bash
git add utils/artifact_state.py tests/test_artifact_state.py
git commit -m "feat(state): restore latest runtime artifact"
```

### Task 4: Overlay Runtime-State Cookies During Environment Export

**Files:**
- Modify: `utils/export_github_env.py`
- Modify: `tests/test_export_github_env.py`

- [ ] **Step 1: Add a failing runtime-state precedence test**

Import `load_cookie_accounts` and append to `BuildEnvironmentTests`:

```python
import tempfile
from pathlib import Path

from utils.export_github_env import (
    build_environment,
    load_cookie_accounts,
)
from utils.runtime_state import write_runtime_state


def test_runtime_state_file_supplies_account_cookie_map(self):
    runtime_state = {
        "version": 1,
        "accounts": {
            "COOKIES_123": [
                {
                    "name": "sessionid",
                    "value": "artifact",
                    "domain": ".douyin.com",
                    "path": "/",
                }
            ]
        },
        "ledger": {},
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "runtime.json"
        write_runtime_state(path, runtime_state)
        accounts = load_cookie_accounts(str(path), "")
    self.assertEqual(accounts, runtime_state["accounts"])

def test_runtime_accounts_override_only_matching_cookie_secret(self):
    result = build_environment(
        {},
        {
            "COOKIES_123": "bootstrap",
            "COOKIES_456": "keep",
            "COOKIE_STATE_KEY": "never-export",
        },
        {
            "COOKIES_123": [
                {
                    "name": "sessionid",
                    "value": "artifact",
                    "domain": ".douyin.com",
                    "path": "/",
                }
            ]
        },
    )
    self.assertEqual(json.loads(result["COOKIES_123"])[0]["value"], "artifact")
    self.assertEqual(result["COOKIES_456"], "keep")
    self.assertNotIn("COOKIE_STATE_KEY", result)
```

- [ ] **Step 2: Verify the new main-path test fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_export_github_env -v
```

Expected: failure because `RUNTIME_STATE_FILE` is not loaded.

- [ ] **Step 3: Load runtime accounts with legacy fallback**

Modify imports and add a pure loader in `utils/export_github_env.py`:

```python
from utils.cookie_state import load_cookie_state, validate_cookie_state
from utils.runtime_state import load_runtime_state


def load_cookie_accounts(runtime_state_file, legacy_cookie_state_file):
    if runtime_state_file:
        return load_runtime_state(runtime_state_file)["accounts"]
    return load_cookie_state(legacy_cookie_state_file)
```

In `main()`, replace direct legacy loading with:

```python
cookie_state = load_cookie_accounts(
    os.getenv("RUNTIME_STATE_FILE", ""),
    os.getenv("COOKIE_STATE_FILE", ""),
)
```

Keep `RESERVED_SECRETS = {"COOKIE_STATE_KEY"}` and keep
`build_environment()` accepting an account-cookie mapping. Do not export the
ledger to `.env` or `$GITHUB_ENV`.

- [ ] **Step 4: Run focused and full tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_export_github_env -v
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the environment overlay**

Run:

```bash
git add utils/export_github_env.py tests/test_export_github_env.py
git commit -m "feat(state): load cookies from runtime artifact"
```

### Task 5: Add Daily At-Most-Once Sending and Immediate State Writes

**Files:**
- Modify: `utils/config.py`
- Modify: `core/tasks.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_tasks.py`

- [ ] **Step 1: Write failing configuration and send-ledger tests**

Add to `tests/test_config.py`:

```python
def test_reads_runtime_state_paths(self):
    original = config_module.config
    config_module.config = None
    try:
        with patch.dict(
            config_module.os.environ,
            {
                "RUNTIME_STATE_FILE": "/tmp/input.json",
                "RUNTIME_STATE_OUTPUT": "/tmp/output.json",
                "RUNTIME_STATE_UNCERTAIN_MARKER": "/tmp/uncertain",
                "LEDGER_TIMEZONE": "Asia/Shanghai",
            },
            clear=False,
        ):
            config = config_module.get_config()
            self.assertEqual(config["runtimeStateFile"], "/tmp/input.json")
            self.assertEqual(config["runtimeStateOutput"], "/tmp/output.json")
            self.assertEqual(
                config["runtimeStateUncertainMarker"],
                "/tmp/uncertain",
            )
            self.assertEqual(config["ledgerTimezone"], "Asia/Shanghai")
    finally:
        config_module.config = original
```

Add focused tests to `tests/test_tasks.py`:

```python
from datetime import datetime

from utils.runtime_state import (
    mark_sent,
    new_runtime_state,
    was_sent,
)


class ExactMessageLocator:
    def __init__(self, counts):
        self.counts = iter(counts)
    def count(self):
        return next(self.counts)


class FakeChatInput:
    def __init__(self):
        self.typed = []
        self.enter_presses = 0
    def type(self, text):
        self.typed.append(text)
    def press(self, key):
        if key == "Enter":
            self.enter_presses += 1


class SendPage:
    def __init__(self, header_name, message_counts):
        self.header = ConversationHeaderLocator(header_name)
        self.messages = ExactMessageLocator(message_counts)
        self.input = FakeChatInput()
    def locator(self, selector):
        if selector == tasks.ACTIVE_CONVERSATION_HEADER_SELECTOR:
            return self.header
        if selector == tasks.CHAT_INPUT_SELECTOR:
            return self.input
        return MarkerLocator(False)
    def get_by_text(self, text, exact):
        return self.messages


class SendOnceTests(unittest.TestCase):
    def test_exactly_one_new_message_is_required(self):
        page = SendPage("Bruno", [2, 3])
        tasks.send_message_once(page, "Bruno", "古德猫宁")
        self.assertEqual(page.input.enter_presses, 1)

    def test_missing_new_message_is_ambiguous_and_not_recorded(self):
        page = SendPage("Bruno", [2, 2])
        with self.assertRaisesRegex(RuntimeError, "无法确认"):
            tasks.send_message_once(page, "Bruno", "古德猫宁")

    def test_pending_targets_excludes_today_sent_ids(self):
        state = new_runtime_state()
        now = datetime.fromisoformat("2026-07-23T06:00:00+08:00")
        mark_sent(state, "11x_y", now)
        self.assertEqual(
            tasks.pending_targets(
                state,
                ["11x_y", "61723137"],
                now.date(),
            ),
            ["61723137"],
        )

    def test_duplicate_nickname_mapping_is_rejected(self):
        mapping = {
            "one": {"nickname": "相同昵称"},
            "two": {"nickname": "相同昵称"},
        }
        with self.assertRaisesRegex(RuntimeError, "唯一"):
            tasks.resolve_target_symbol(
                "相同昵称",
                ["one", "two"],
                mapping,
                "short_id",
            )

    def test_authentication_failure_does_not_capture_page_html(self):
        self.assertFalse(
            tasks.should_capture_diagnostic_html(
                "authentication_required"
            )
        )
        self.assertTrue(
            tasks.should_capture_diagnostic_html(
                "friend_list_not_ready"
            )
        )
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_config.ValidateOnlyConfigTests \
  tests.test_tasks.SendOnceTests -v
```

Expected: failures for absent runtime-state config, `CHAT_INPUT_SELECTOR`,
`send_message_once()`, and `pending_targets()`.

- [ ] **Step 3: Parse runtime configuration**

Add to the `config` dictionary in `utils/config.py`:

```python
"runtimeStateFile": os.getenv("RUNTIME_STATE_FILE", ""),
"runtimeStateOutput": os.getenv("RUNTIME_STATE_OUTPUT", ""),
"runtimeStateUncertainMarker": os.getenv(
    "RUNTIME_STATE_UNCERTAIN_MARKER",
    "",
),
"ledgerTimezone": os.getenv("LEDGER_TIMEZONE", "Asia/Shanghai"),
```

- [ ] **Step 4: Add pure pending and verified-send helpers**

In `core/tasks.py`, import:

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from utils.runtime_state import (
    load_runtime_state,
    mark_sent,
    new_runtime_state,
    set_account_cookies,
    was_sent,
    write_runtime_state,
)
```

Define:

```python
CHAT_INPUT_SELECTOR = "xpath=//div[contains(@class, 'chat-input-')]"


class UncertainSendError(RuntimeError):
    pass


def should_capture_diagnostic_html(reason):
    return reason != "authentication_required"


def pending_targets(state, targets, day):
    return [
        target
        for target in targets
        if not was_sent(state, target, day)
    ]


def resolve_target_symbol(target_name, targets, user_id_dict, mode):
    if mode != "short_id":
        return target_name
    matches = [
        short_id
        for short_id, info in user_id_dict.items()
        if info.get("nickname") == target_name
        and short_id in targets
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"好友 {target_name!r} 无法唯一映射到目标抖音号"
        )
    return matches[0]


def send_message_once(page, expected_name, message):
    ensure_active_conversation(page, expected_name)
    exact_messages = page.get_by_text(message, exact=True)
    before_count = exact_messages.count()
    chat_input = page.locator(CHAT_INPUT_SELECTOR)
    for index, line in enumerate(message.split("\\n")):
        chat_input.type(line)
        if index < len(message.split("\\n")) - 1:
            chat_input.press("Shift+Enter")
    ensure_active_conversation(page, expected_name)
    chat_input.press("Enter")
    after_count = exact_messages.count()
    if after_count != before_count + 1:
        raise UncertainSendError(
            f"无法确认给 {expected_name} 的消息只新增了一条"
        )


def persist_verified_send(
    state,
    unique_id,
    target,
    cookies,
    sent_at,
    output_path,
):
    mark_sent(state, target, sent_at)
    set_account_cookies(state, unique_id, cookies)
    if output_path:
        write_runtime_state(output_path, state)


def mark_uncertain_send(path):
    if not path:
        return
    marker = Path(path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch(mode=0o600, exist_ok=True)
```

Do not wrap `send_message_once()` in `retry_operation()`.
In `save_page_diagnostics()`, wrap the existing `page.content()` write with
`if should_capture_diagnostic_html(reason):` so authentication failures never
store page HTML.

- [ ] **Step 5: Carry target IDs through selection**

Replace the `next(...)` nickname lookup inside
`scroll_and_select_user()` with:

```python
targetSymbol = resolve_target_symbol(
    targetName,
    targets,
    userIDDict,
    matchMode,
)
```

Change the generator yield in `scroll_and_select_user()` from:

```python
yield targetName
```

to:

```python
yield targetSymbol, targetName
```

Update the caller to iterate with:

```python
for target_symbol, target_name in scroll_and_select_user(
    page,
    username,
    targets,
):
```

- [ ] **Step 6: Persist state after each verified send**

Change `do_user_task()` to accept `unique_id`, `runtime_state`, and
`runtime_state_output`. At the beginning of a non-validation run, compute:

```python
now = datetime.now(ZoneInfo(config["ledgerTimezone"]))
targets = pending_targets(runtime_state, targets, now.date())
```

Wrap the send so an unverifiable acceptance creates a gap marker:

```python
try:
    send_message_once(page, target_name, message)
except UncertainSendError:
    mark_uncertain_send(config["runtimeStateUncertainMarker"])
    raise

persist_verified_send(
    runtime_state,
    unique_id,
    target_symbol,
    context.cookies(),
    datetime.now(ZoneInfo(config["ledgerTimezone"])),
    runtime_state_output,
)
time.sleep(config["messageSendIntervalSeconds"])
```

In validation-only mode, refresh the account cookies and write the state once
after the friend-list check. In `runTasks()`, load:

```python
runtime_state = (
    load_runtime_state(config["runtimeStateFile"])
    if config["runtimeStateFile"]
    else new_runtime_state()
)
```

Pass the shared state and output path to each account task. Remove
`COOKIE_STATE_OUTPUT` writes from `runTasks()` after all tests have been
migrated; retain `utils/cookie_state.py` only for legacy input compatibility.

- [ ] **Step 7: Add a partial-failure persistence test**

Add to `tests/test_tasks.py`:

```python
@patch.object(tasks, "write_runtime_state")
def test_verified_send_is_persisted_immediately(self, write_state):
    state = new_runtime_state()
    sent_at = datetime.fromisoformat("2026-07-23T06:00:00+08:00")
    cookies = [
        {
            "name": "sessionid",
            "value": "rotated",
            "domain": ".douyin.com",
            "path": "/",
        }
    ]
    tasks.persist_verified_send(
        state,
        "90530392137",
        "11x_y",
        cookies,
        sent_at,
        "/tmp/runtime-output.json",
    )
    self.assertTrue(was_sent(state, "11x_y", sent_at.date()))
    self.assertFalse(was_sent(state, "61723137", sent_at.date()))
    write_state.assert_called_once_with(
        "/tmp/runtime-output.json",
        state,
    )

def test_unverified_send_creates_uncertainty_marker(self):
    with tempfile.TemporaryDirectory() as temp_dir:
        marker = Path(temp_dir) / "uncertain"
        tasks.mark_uncertain_send(marker)
        self.assertTrue(marker.exists())
```

This test proves that the durable write happens immediately after each
verified target; a later target failure cannot remove the first ledger entry.
Import `tempfile` and `Path` in the test module.

- [ ] **Step 8: Run focused and full tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_config tests.test_tasks -v
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected: all tests pass and no whitespace errors.

- [ ] **Step 9: Commit the sending guard**

Run:

```bash
git add utils/config.py core/tasks.py tests/test_config.py tests/test_tasks.py
git commit -m "feat(send): persist daily at-most-once ledger"
```

### Task 6: Add the One-Time Local QR Bootstrap

**Files:**
- Create: `scripts/bootstrap_github_login.py`
- Create: `tests/test_bootstrap_github_login.py`

- [ ] **Step 1: Write failing secret-transport tests**

Create `tests/test_bootstrap_github_login.py`:

```python
import subprocess
import unittest
from unittest.mock import patch

from scripts.bootstrap_github_login import set_environment_secret


class BootstrapSecretTests(unittest.TestCase):
    @patch("scripts.bootstrap_github_login.subprocess.run")
    def test_secret_is_passed_only_through_stdin(self, run):
        set_environment_secret(
            "COOKIES_123",
            "sensitive-json",
            "owner/repo",
            "user-data",
        )
        args = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertNotIn("sensitive-json", args)
        self.assertEqual(kwargs["input"], "sensitive-json")
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertTrue(kwargs["check"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_bootstrap_github_login -v
```

Expected: import failure because the bootstrap module does not exist.

- [ ] **Step 3: Implement standard-input secret transport**

Create `scripts/bootstrap_github_login.py` with:

```python
import argparse
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    str(Path(__file__).resolve().parents[1] / "chrome"),
)
CHAT_URL = (
    "https://creator.douyin.com/creator-micro/data/following/chat"
)
FRIENDS_TAB = 'role=tab[name="朋友私信"]'
FRIEND_ITEM = (
    'xpath=//div[@role="tab-panel" and @aria-hidden="false"]'
    '//li[contains(@class, "semi-list-item")]'
)


def set_environment_secret(name, value, repository, environment):
    subprocess.run(
        [
            "gh",
            "secret",
            "set",
            name,
            "--repo",
            repository,
            "--env",
            environment,
        ],
        input=value,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def capture_logged_in_cookies(timeout_seconds):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(CHAT_URL)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            tab = page.locator(FRIENDS_TAB)
            if tab.count() and tab.first.is_visible():
                tab.first.click()
                page.locator(FRIEND_ITEM).first.wait_for(
                    state="visible",
                    timeout=15000,
                )
                cookies = context.cookies()
                browser.close()
                return cookies
            page.wait_for_timeout(500)
        browser.close()
        raise RuntimeError("扫码登录超时或好友列表未加载")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--environment", default="user-data")
    parser.add_argument("--unique-id", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    cookies = capture_logged_in_cookies(args.timeout)
    cookie_name = f"COOKIES_{args.unique_id}".upper()
    set_environment_secret(
        cookie_name,
        json.dumps(cookies, ensure_ascii=False, separators=(",", ":")),
        args.repository,
        args.environment,
    )
    set_environment_secret(
        "COOKIE_STATE_KEY",
        secrets.token_urlsafe(48),
        args.repository,
        args.environment,
    )
    print("GitHub 登录引导完成；Cookie 和密钥未输出。")


if __name__ == "__main__":
    main()
```

Do not add debug logging of cookies, subprocess input, page HTML, or request
headers.

- [ ] **Step 4: Add timeout and failed-secret tests**

Append to `BootstrapSecretTests`:

```python
@patch("scripts.bootstrap_github_login.subprocess.run")
def test_failed_secret_upload_does_not_put_value_in_command(self, run):
    run.side_effect = subprocess.CalledProcessError(
        1,
        ["gh", "secret", "set", "COOKIES_123"],
    )
    with self.assertRaises(subprocess.CalledProcessError) as raised:
        set_environment_secret(
            "COOKIES_123",
            "sensitive-json",
            "owner/repo",
            "user-data",
        )
    self.assertNotIn("sensitive-json", str(raised.exception))

@patch("scripts.bootstrap_github_login.time.monotonic")
@patch("scripts.bootstrap_github_login.sync_playwright")
def test_login_timeout_raises_without_uploading_secrets(
    self,
    sync_playwright,
    monotonic,
):
    monotonic.side_effect = [0, 0, 2]
    page = sync_playwright.return_value.__enter__.return_value
    browser = page.chromium.launch.return_value
    login_page = browser.new_context.return_value.new_page.return_value
    login_page.locator.return_value.count.return_value = 0
    with self.assertRaisesRegex(RuntimeError, "扫码登录超时"):
        capture_logged_in_cookies(1)
```

Import `capture_logged_in_cookies` in the test module. The mocked clock enters
the loop once and then crosses the deadline.

- [ ] **Step 5: Run focused and full tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_bootstrap_github_login -v
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit the bootstrap command**

Run:

```bash
git add scripts/bootstrap_github_login.py \
  tests/test_bootstrap_github_login.py
git commit -m "feat(auth): add secure GitHub login bootstrap"
```

### Task 7: Replace Cache Persistence with Encrypted Artifacts

**Files:**
- Modify: `.github/workflows/schedule.yml`
- Modify: `tests/test_workflow_cookie_state.py`

- [ ] **Step 1: Replace cache assertions with failing artifact assertions**

Update `tests/test_workflow_cookie_state.py` to assert:

```python
def test_serializes_runs_without_cancelling_active_send(self):
    self.assertIn("concurrency:", self.workflow)
    self.assertIn("group: douyin-spark-flow", self.workflow)
    self.assertIn("cancel-in-progress: false", self.workflow)

def test_restores_runtime_state_from_artifact(self):
    self.assertNotIn("actions/cache@", self.workflow)
    self.assertIn("python -m utils.artifact_state restore", self.workflow)
    self.assertIn("RUNTIME_STATE_FILE=", self.workflow)
    self.assertIn("bootstrap_state:", self.workflow)

def test_uploads_only_encrypted_state_for_ninety_days(self):
    self.assertIn("uses: actions/upload-artifact@v4", self.workflow)
    self.assertIn(
        "name: douyin-runtime-state-${{ github.run_id }}",
        self.workflow,
    )
    self.assertIn("path: .runtime-state/state.enc", self.workflow)
    self.assertIn("retention-days: 90", self.workflow)
    self.assertIn("if: ${{ always()", self.workflow)
    self.assertIn("RUNTIME_STATE_UNCERTAIN_MARKER:", self.workflow)
    self.assertIn(
        "refusing to publish successor artifact",
        self.workflow,
    )

def test_runtime_permissions_are_read_only(self):
    self.assertIn("permissions:", self.workflow)
    self.assertIn("actions: read", self.workflow)
    self.assertIn("contents: read", self.workflow)
```

Keep the validation-only and package-module assertions.

- [ ] **Step 2: Verify RED against the cache workflow**

Run:

```bash
.venv/bin/python -m unittest tests.test_workflow_cookie_state -v
```

Expected: artifact, concurrency, and permission assertions fail.

- [ ] **Step 3: Add workflow inputs, permissions, and concurrency**

At workflow level add:

```yaml
permissions:
  actions: read
  contents: read

concurrency:
  group: douyin-spark-flow
  cancel-in-progress: false
```

Under `workflow_dispatch.inputs`, retain `validate_only` and add:

```yaml
bootstrap_state:
  description: Ignore old state and bootstrap a new encrypted artifact
  required: false
  default: false
  type: boolean
```

- [ ] **Step 4: Restore and decrypt fail-closed**

Replace the `actions/cache` restore with:

```yaml
- name: Restore encrypted runtime state artifact
  env:
    GH_TOKEN: ${{ github.token }}
  run: |
    args=(
      restore
      --repository "$GITHUB_REPOSITORY"
      --workflow schedule.yml
      --run-id "$GITHUB_RUN_ID"
      --output .runtime-state/state.enc
    )
    if [ "${{ inputs.bootstrap_state || 'false' }}" = "true" ]; then
      args+=(--allow-bootstrap)
    fi
    python -m utils.artifact_state "${args[@]}"

- name: Decrypt runtime state
  env:
    COOKIE_STATE_KEY: ${{ secrets.COOKIE_STATE_KEY }}
  run: |
    mkdir -p .runtime-state
    if [ -z "$COOKIE_STATE_KEY" ]; then
      echo "COOKIE_STATE_KEY is required" >&2
      exit 1
    fi
    if [ -s .runtime-state/state.enc ]; then
      openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
        -pass env:COOKIE_STATE_KEY \
        -in .runtime-state/state.enc \
        -out .runtime-state/input.json
      chmod 600 .runtime-state/input.json
      python -m utils.runtime_state validate .runtime-state/input.json
      echo "RUNTIME_STATE_FILE=$GITHUB_WORKSPACE/.runtime-state/input.json" \
        >> "$GITHUB_ENV"
    elif [ "${{ inputs.bootstrap_state || 'false' }}" != "true" ]; then
      echo "Runtime state is missing outside bootstrap" >&2
      exit 1
    fi
```

Do not fall back to the bootstrap Cookie Secret after a restore or decrypt
failure.

- [ ] **Step 5: Run with runtime output and no send retries**

Set the application environment:

```yaml
- name: Run DouYin Spark Flow
  env:
    VALIDATE_ONLY: ${{ inputs.validate_only || 'false' }}
    RUNTIME_STATE_OUTPUT: .runtime-state/output.json
    RUNTIME_STATE_UNCERTAIN_MARKER: .runtime-state/uncertain
    LEDGER_TIMEZONE: Asia/Shanghai
  run: python main.py
```

- [ ] **Step 6: Encrypt and upload the latest valid state even after partial failure**

Add:

```yaml
- name: Encrypt latest runtime state
  id: encrypt_state
  if: ${{ always() }}
  env:
    COOKIE_STATE_KEY: ${{ secrets.COOKIE_STATE_KEY }}
  run: |
    if [ ! -s .runtime-state/output.json ]; then
      echo "state_ready=false" >> "$GITHUB_OUTPUT"
      exit 0
    fi
    if [ -e .runtime-state/uncertain ]; then
      echo "Uncertain send state; refusing to publish successor artifact" >&2
      echo "state_ready=false" >> "$GITHUB_OUTPUT"
      exit 0
    fi
    if [ -z "$COOKIE_STATE_KEY" ]; then
      echo "COOKIE_STATE_KEY is required" >&2
      exit 1
    fi
    python -m utils.runtime_state validate .runtime-state/output.json
    openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
      -pass env:COOKIE_STATE_KEY \
      -in .runtime-state/output.json \
      -out .runtime-state/state.enc
    echo "state_ready=true" >> "$GITHUB_OUTPUT"

- name: Upload encrypted runtime state
  if: ${{ always() && steps.encrypt_state.outputs.state_ready == 'true' }}
  uses: actions/upload-artifact@v4
  with:
    name: douyin-runtime-state-${{ github.run_id }}
    path: .runtime-state/state.enc
    retention-days: 90
    if-no-files-found: error

- name: Remove plaintext runtime state
  if: ${{ always() }}
  run: |
    rm -f .runtime-state/input.json \
      .runtime-state/output.json \
      .runtime-state/uncertain
    rm -f .env
```

Keep the diagnostic `run-logs` artifact separate and ensure it cannot include
`.runtime-state/`.

- [ ] **Step 7: Run workflow and full tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_workflow_cookie_state -v
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected: all tests pass, no cache assertions remain, and no whitespace errors
are reported.

- [ ] **Step 8: Commit the workflow migration**

Run:

```bash
git add .github/workflows/schedule.yml \
  tests/test_workflow_cookie_state.py
git commit -m "feat(ci): persist encrypted runtime artifacts"
```

### Task 8: Bootstrap, Push, and Verify Two Cloud Runs

**Files:**
- No new tracked files.
- External changes: GitHub Environment Secrets, workflow enabled state, and
  the existing local Codex automation status.

- [ ] **Step 1: Run final local verification**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile \
  utils/runtime_state.py \
  utils/artifact_state.py \
  scripts/bootstrap_github_login.py \
  core/tasks.py
git diff --check
git status --short
```

Expected: all tests pass; compilation and diff checks are silent; only the
known untracked `tests/__init__.py` remains outside committed work.

- [ ] **Step 2: Push the reconciled branch to main**

Run:

```bash
git push origin HEAD:main
```

Expected: fast-forward update of `origin/main`. If rejected, fetch and merge
the new remote main, rerun the full suite, then retry; never force-push.

- [ ] **Step 3: Start the local QR bootstrap**

Run:

```bash
.venv/bin/python scripts/bootstrap_github_login.py \
  --repository ljl1211420042-cyber/DouYinSparkFlow \
  --environment user-data \
  --unique-id 90530392137 \
  --timeout 300
```

Expected: a visible browser opens. The user scans once. The command ends with
`GitHub 登录引导完成；Cookie 和密钥未输出。` and prints no secret value.

- [ ] **Step 4: Enable the workflow and dispatch the first no-send bootstrap**

Run:

```bash
gh workflow enable schedule.yml
gh workflow run schedule.yml \
  -f validate_only=true \
  -f bootstrap_state=true
```

Wait for completion with `gh run watch`. Expected:

- friend list validation succeeds;
- zero `准备发送消息给好友` markers;
- one `douyin-runtime-state-<run_id>` artifact is uploaded; and
- no Cookie or encryption-key values appear in logs.

If this run fails, disable the workflow immediately:

```bash
gh workflow disable schedule.yml
```

- [ ] **Step 5: Dispatch the second no-send restore validation**

Run:

```bash
gh workflow run schedule.yml \
  -f validate_only=true \
  -f bootstrap_state=false
```

Expected:

- `Encrypted runtime state restored`;
- successful decryption and runtime-state validation;
- friend list validation succeeds;
- zero send markers; and
- a successor encrypted artifact is uploaded.

If this run fails, disable the workflow and do not enable scheduled sends.

- [ ] **Step 6: Prevent double scheduling**

After both GitHub validations pass, pause the existing local Codex automation
named `抖音续火花（本机防重复）`. Confirm the GitHub workflow remains enabled.
Do not delete the local automation; keep it paused as a fallback.

- [ ] **Step 7: Report verified status**

Report:

- exact test count and command;
- both validation run IDs and conclusions;
- confirmation that both contained zero sends;
- the encrypted artifact names;
- GitHub workflow enabled state;
- local automation paused state; and
- the remaining limitation that Douyin can still request a fresh QR login
  because GitHub runners change device and IP.

## Pre-Merge Review Hardening Amendment

The implementation review added these mandatory fail-closed controls:

- arm `.runtime-state/uncertain` before entering the send critical section and
  clear it only after message verification and atomic ledger persistence;
- scope matching-message verification to the active conversation panel and
  wait for the UI to render the new message;
- reject `GITHUB_RUN_ATTEMPT > 1` because reruns reuse `GITHUB_RUN_ID`;
- require `bootstrap_state=true` to be paired with `validate_only=true`;
- remove the write-enabled third-party keepalive job; and
- write `.env` with owner-only permissions.
