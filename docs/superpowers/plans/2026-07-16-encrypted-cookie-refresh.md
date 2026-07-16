# Encrypted Cookie Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist refreshed Douyin cookies between successful GitHub Actions runs without a PAT or plaintext cloud storage.

**Architecture:** A focused cookie-state utility validates and atomically writes Playwright cookie maps. The task runner exports cookies only after all accounts succeed, while the workflow encrypts the state with an Environment Secret and saves only the ciphertext in Actions cache.

**Tech Stack:** Python 3.11, Playwright, unittest, GitHub Actions, OpenSSL AES-256-CBC/PBKDF2, actions/cache v4.

---

### Task 1: Cookie-state format

**Files:**
- Create: `utils/cookie_state.py`
- Create: `tests/test_cookie_state.py`

- [ ] **Step 1: Write failing validation and atomic-write tests**

Test that valid `COOKIES_<id>` maps round-trip, unsupported cookie fields are removed, malformed keys and cookie values raise `ValueError`, and the written file has mode `0600`.

- [ ] **Step 2: Verify the tests fail because the module is missing**

Run: `.venv/bin/python -m unittest tests.test_cookie_state -v`

Expected: `ModuleNotFoundError: No module named 'utils.cookie_state'`.

- [ ] **Step 3: Implement the minimal utility**

Provide:

```python
COOKIE_FIELDS = {
    "domain", "expires", "httpOnly", "name", "path",
    "sameSite", "secure", "value",
}

def cookie_key(unique_id): ...
def normalize_cookies(cookies): ...
def validate_cookie_state(state): ...
def load_cookie_state(path): ...
def write_cookie_state(path, state): ...
```

Use a same-directory temporary file, `os.chmod(..., 0o600)`, and
`os.replace()` for atomic writes.

- [ ] **Step 4: Verify focused and full tests pass**

Run:

```bash
.venv/bin/python -m unittest tests.test_cookie_state -v
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Expected: all tests pass.

### Task 2: State precedence during environment export

**Files:**
- Modify: `utils/export_github_env.py`
- Create: `tests/test_export_github_env.py`

- [ ] **Step 1: Write failing precedence tests**

Call a pure `build_environment(vars_map, secrets_map, cookie_state)` helper and
assert that cached `COOKIES_<id>` values override the matching secret while
unrelated variables and bootstrap cookie secrets remain unchanged.

- [ ] **Step 2: Verify the test fails because the helper is absent**

Run: `.venv/bin/python -m unittest tests.test_export_github_env -v`

Expected: import or attribute failure for `build_environment`.

- [ ] **Step 3: Implement state loading and overlay**

Read `COOKIE_STATE_FILE` only when configured. Validate with
`load_cookie_state()`, merge after secrets, and serialize cookie arrays with
`json.dumps(..., ensure_ascii=False)` before writing `$GITHUB_ENV` and `.env`.

- [ ] **Step 4: Verify focused and full tests pass**

Run both focused unittest and full discovery. Expected: zero failures.

### Task 3: Export refreshed cookies after a complete task run

**Files:**
- Modify: `core/tasks.py`
- Modify: `utils/config.py`
- Modify: `tests/test_tasks.py`

- [ ] **Step 1: Write failing state-collection tests**

Test a pure helper that adds normalized context cookies under
`COOKIES_<unique_id>`. Test that validation-only mode verifies the friend list,
returns refreshed cookies, and never calls the message-sending loop.

- [ ] **Step 2: Verify the focused test fails for the missing helper**

Run: `.venv/bin/python -m unittest tests.test_tasks -v`.

- [ ] **Step 3: Return and persist refreshed cookies**

Change `do_user_task()` to return `context.cookies()` before closing the
context. Accumulate results in `runTasks()` and call `write_cookie_state()` at
`COOKIE_STATE_OUTPUT` only after every account task succeeds. Parse
`VALIDATE_ONLY` in `utils/config.py`; in that mode wait for the friends tab and
one conversation item, then return without selecting a target.

- [ ] **Step 4: Verify the complete suite**

Run unittest discovery. Expected: all existing and new tests pass.

### Task 4: GitHub Actions encrypted cache

**Files:**
- Modify: `.github/workflows/schedule.yml`
- Create: `tests/test_workflow_cookie_state.py`

- [ ] **Step 1: Write a failing workflow structure test**

Assert the workflow contains `actions/cache@v4`, a unique run-id cache key,
restore prefix, decrypt fallback, `COOKIE_STATE_OUTPUT`, success-only encryption,
plaintext cleanup, and a boolean `validate_only` dispatch input wired to
`VALIDATE_ONLY`.

- [ ] **Step 2: Verify the test fails against the current workflow**

Run: `.venv/bin/python -m unittest tests.test_workflow_cookie_state -v`.

- [ ] **Step 3: Add restore, decrypt, run, and encrypt steps**

Restore `.cookie-state/state.enc`; decrypt it to `latest.json` with
`openssl enc -d -aes-256-cbc -pbkdf2 -pass env:COOKIE_STATE_KEY`; run the app
with output `.cookie-state/refreshed.json`; encrypt that file back to
`state.enc` only after success; remove plaintext files. Add the manual
`validate_only` input and pass it to the process environment.

- [ ] **Step 4: Verify YAML behavior and the full suite**

Run the focused workflow test, unittest discovery, and `git diff --check`.
Expected: all pass with no whitespace errors.

### Task 5: Configure and validate cloud execution

**Files:**
- No tracked file additions beyond Tasks 1-4.

- [ ] **Step 1: Create the encryption key**

Generate 32 random bytes locally, base64 encode them, and pipe the value directly
to the `COOKIE_STATE_KEY` Environment Secret without printing it.

- [ ] **Step 2: Commit and push the implementation**

Stage only the feature files, preserving unrelated untracked files. Commit with
`feat(auth): persist refreshed cookies` and push `HEAD:main`.

- [ ] **Step 3: Bootstrap the encrypted cache without sending**

Dispatch the workflow with `validate_only=true` while leaving the full target
configuration unchanged. Confirm the run reports zero send markers.

- [ ] **Step 4: Verify the first cache-backed run**

Confirm run success, zero send markers, no authentication or friend-list
failure, and the presence of one `douyin-cookie-state-` cache entry.

- [ ] **Step 5: Verify cached authentication without sending**

Dispatch `validate_only=true` a second time. Confirm the workflow reports that
cached state was restored, loads the friend list, sends zero messages, and keeps
the full target count configured.
