# Encrypted Cookie Refresh Design

## Goal

Keep the scheduled Douyin workflow authenticated after Douyin rotates session
cookies, without adding a high-privilege GitHub personal access token.

## Chosen Approach

Persist the refreshed Playwright cookie set in GitHub Actions cache. The cache
contains only an encrypted file. A dedicated `COOKIE_STATE_KEY` environment
secret encrypts and decrypts that file with OpenSSL AES-256-CBC and PBKDF2.

Two alternatives were rejected:

- Updating the GitHub Environment Secret after every run requires a PAT that
  can write repository or environment secrets.
- Running a persistent Chrome profile locally avoids cookie export but requires
  the Mac to stay powered on and connected.

## Data Flow

1. The workflow restores the newest cache entry matching
   `douyin-cookie-state-`.
2. If both the encrypted state and `COOKIE_STATE_KEY` exist, the workflow
   decrypts the state into a temporary JSON file.
3. `utils/export_github_env.py` exports repository variables and secrets as it
   does today, then overlays any valid `COOKIES_<unique_id>` entries from the
   decrypted state. Missing entries continue to use the bootstrap GitHub
   Secret.
4. Each successful account task reads `context.cookies()` before closing its
   Playwright context.
5. Only after every configured account succeeds, the process atomically writes
   a refreshed cookie-state JSON file.
6. The workflow encrypts the refreshed file and removes plaintext. The cache
   post-step saves the encrypted state only when the job succeeds.

## Components

### `utils/cookie_state.py`

Owns the cookie-state format, validation, normalization, and atomic writes.
The on-disk JSON object maps `COOKIES_<unique_id>` to a Playwright-compatible
cookie list. Unknown top-level keys, non-list values, and malformed cookies are
rejected instead of being injected into the environment.

### `utils/export_github_env.py`

Reads the optional `COOKIE_STATE_FILE`. Valid state overrides only matching
cookie environment variables after GitHub secrets have been loaded. An absent
state file is the normal bootstrap path.

### `core/tasks.py`

Returns the browser context's latest cookies after a successful account task.
`runTasks()` accumulates all successful account states and writes
`COOKIE_STATE_OUTPUT` only after the full run completes. A `VALIDATE_ONLY`
mode verifies authentication and friend-list loading, refreshes cookie state,
and exits without selecting a target or sending a message.

### `.github/workflows/schedule.yml`

Restores the encrypted cache, decrypts it before environment export, provides
the output path to `main.py`, encrypts refreshed state after success, and lets
`actions/cache` save the encrypted file. Manual dispatch exposes a boolean
`validate_only` input so cache restoration can be tested without duplicate
messages.

## Failure Handling

- Missing encryption key: log a warning and use the bootstrap Cookie Secret.
- Missing cache: normal first-run behavior; use the bootstrap Cookie Secret.
- Decryption failure: delete plaintext remnants and use the bootstrap Secret.
- Invalid decrypted JSON: fail during environment export rather than inject
  untrusted or malformed cookie data.
- Douyin task failure: `main.py` exits nonzero, no refreshed state is encrypted,
  and the previous successful cache remains the newest usable state.
- Encryption failure: fail the workflow so an unusable cache is not saved.

## Security

- No PAT is stored.
- `COOKIE_STATE_KEY` is an Environment Secret and is never printed.
- Plaintext cookie-state files are created with owner-only permissions and are
  removed after encryption.
- Workflow artifacts continue to contain diagnostics only, not cookie state.

## Verification

- Unit tests cover cookie normalization, invalid-state rejection, atomic state
  writes, state-over-secret precedence, and no-send validation mode.
- Existing authentication and friend-list tests remain green.
- Workflow YAML is parsed and checked for cache, decrypt, output, and encrypt
  steps.
- Two manual validation-only workflow runs must complete successfully. The
  first bootstraps and saves encrypted state; the second restores that state.
  Both must load the friend list and send zero messages.
