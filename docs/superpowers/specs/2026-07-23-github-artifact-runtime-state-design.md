# GitHub Artifact Runtime State Design

## Goal

Run the Douyin streak-maintenance task on GitHub-hosted runners while the
user's Mac is powered off, without printing login cookies, resending to a
target during normal retries, or depending on GitHub Actions cache retention.

The solution must preserve the existing fixed message, target list, eight
second minimum interval, exact conversation-title guard, and diagnostic logs.

## Constraints

- Every GitHub-hosted job starts on a new virtual machine. Browser profile
  files do not survive between jobs.
- Douyin can invalidate a session because of age, device changes, IP changes,
  or risk controls. No workflow can guarantee that a cookie remains valid.
- GitHub Secrets cannot be read back. They are a bootstrap source, not a
  mutable runtime database.
- The repository must never contain plaintext cookies or encryption keys.
- A hard runner termination after a message is accepted but before any state
  is uploaded creates an unavoidable uncertainty window. The next run must
  detect that the newer run has no successor state artifact and stop before
  sending. Recovery then requires a manual audit or a fresh bootstrap.

## Considered Approaches

### Manual Cookie Secret Only

Store the current cookies in `COOKIES_<unique_id>` and use them on every run.
This is simple but requires repeated manual updates and does not retain
cookies rotated by Douyin.

### Encrypted Artifact Runtime State

Bootstrap once from a locally scanned login, then keep refreshed cookies and
the send ledger in an encrypted workflow artifact. Each run downloads the
newest unexpired state artifact, decrypts it, runs the task, and uploads a new
encrypted state.

This is the chosen approach because artifacts have explicit retention and can
be discovered across workflow runs. It also avoids a high-privilege personal
access token.

### Persistent Cloud Browser

Run a fixed browser profile on a VPS. This provides the most stable device
identity but adds server cost and administration. It remains the fallback if
GitHub runner IP or device churn repeatedly invalidates Douyin sessions.

## Architecture

### One-Time Local Bootstrap

A local bootstrap command launches a dedicated visible Chromium context. The
user scans the Douyin login QR code, and the command verifies that the creator
chat friend list loads.

After verification, the command:

1. reads cookies from only that dedicated Playwright context;
2. generates a fresh random `COOKIE_STATE_KEY`;
3. sends the cookie JSON directly to the `COOKIES_<unique_id>` GitHub
   Environment Secret through `gh secret set` standard input;
4. sends the encryption key directly to the `COOKIE_STATE_KEY` Environment
   Secret through standard input; and
5. closes the context and removes any owner-only temporary files.

Neither secret value is printed, included in command arguments, committed, or
written to workflow logs.

### Runtime State

The decrypted runtime-state JSON has a versioned structure:

```json
{
  "version": 1,
  "accounts": {
    "COOKIES_90530392137": []
  },
  "ledger": {
    "2026-07-23": {
      "<sha256-target-id>": {
        "status": "sent",
        "sent_at": "2026-07-23T06:02:11+08:00"
      }
    }
  }
}
```

The ledger stores a SHA-256 target identifier rather than a nickname or raw
Douyin ID. The state validator rejects unsupported versions, unknown
top-level fields, malformed cookies, invalid dates, and invalid ledger
entries.

The plaintext file uses mode `0600`, is written atomically, and is deleted
after encryption. Only the encrypted state is uploaded.

### Artifact Restore

The workflow grants only `contents: read` and `actions: read`. It queries the
repository Actions Artifacts API with the workflow `GITHUB_TOKEN`, selects the
newest unexpired artifact whose name starts with
`douyin-runtime-state-`, and downloads it.

If no artifact exists, the workflow uses the bootstrap Cookie Secret. If an
artifact exists but cannot be downloaded, decrypted, or validated, the run
fails before sending. It does not silently fall back to an older plaintext or
bootstrap cookie because that could reintroduce stale ledger data.

### Sending and Idempotency

The workflow has a single concurrency group and does not cancel an in-progress
run. Only one scheduled or manual send run can execute at a time.

For every target:

1. compute the target hash and check today's ledger;
2. if already recorded as sent, skip it;
3. resolve the exact Douyin account and verify mutual-follow status;
4. switch the conversation and require the right-side conversation title to
   equal the resolved nickname exactly;
5. recheck the conversation title, send one message, and verify one new
   outgoing message appeared; and
6. atomically record the target as sent immediately after verification.

No send operation is automatically retried. A failed target is reported and
left unrecorded. If verification cannot prove whether the message was
accepted, the run fails and does not upload a successor state for that
uncertain operation.

### State Upload

The task writes the latest cookies and ledger after each verified send. The
workflow's final state step runs even when the application reports a partial
failure, provided a valid plaintext state file exists. It encrypts the latest
atomic state and uploads it as
`douyin-runtime-state-${{ github.run_id }}` with 90-day retention.

If the runner is cancelled or destroyed before the upload step, the next run
compares completed workflow runs with state-artifact run IDs. A newer run
without a state artifact is an uncertainty gap, so the next run fails before
sending. It never guesses in favor of sending.

### Validation and Activation

The current scheduled workflow stays disabled during deployment.

1. Run the local bootstrap.
2. Dispatch `validate_only=true`; it must load the friend list, send zero
   messages, and upload the first encrypted artifact.
3. Dispatch `validate_only=true` again; it must restore and decrypt the first
   artifact, load the friend list, send zero messages, and upload a successor.
4. Confirm the logs contain no cookie values or send markers.
5. Re-enable the daily schedule only after both validations pass.

## Components

### `utils/runtime_state.py`

Owns the versioned cookies-plus-ledger format, validation, target hashing,
atomic writes, and daily sent checks.

### `utils/export_github_env.py`

Loads the optional validated runtime state. Its cookie entries override only
matching bootstrap Cookie Secrets.

### `core/tasks.py`

Checks the ledger before selection, verifies exact account and conversation
identity, verifies exactly one new outgoing message, sends without automatic
retry, and persists state after each verified result.

### `scripts/bootstrap_github_login.py`

Owns the visible one-time QR login and secret upload. It never logs cookie or
key values.

### `.github/workflows/schedule.yml`

Owns artifact discovery, restore, decrypt, concurrency, execution, final
encryption, artifact upload, and the two-step manual validation path.

## Failure Handling

- No artifact on first run: use the bootstrap Cookie Secret.
- Artifact restore, decrypt, or validation failure: fail before sending.
- Expired Douyin session: fail before sending and request a new local
  bootstrap.
- Completed workflow newer than the latest state artifact: fail before
  sending and request a manual audit or fresh bootstrap.
- Target cannot be uniquely resolved: skip and report.
- Conversation title mismatch: skip and report.
- Message acceptance cannot be verified: fail without retrying the send.
- Partial task failure: encrypt and upload the latest valid atomic state.
- Encryption or upload failure: fail the workflow and retain the prior
  artifact as the newest usable state.
- Overlapping manual and scheduled runs: serialize through workflow
  concurrency.

## Security

- Cookies and encryption keys enter GitHub only as Environment Secrets or
  encrypted artifact bytes.
- Secret values are passed through standard input and are never echoed.
- Plaintext runtime state is owner-only and deleted after encryption.
- Diagnostics must not include page HTML, request headers, local storage, or
  cookies after authentication failures.
- The workflow uses the default `GITHUB_TOKEN`; no personal access token is
  added.
- The ledger exposes only hashed target identifiers inside encrypted state.

## Testing

Unit tests cover:

- runtime-state validation and atomic owner-only writes;
- target hashing and daily ledger checks;
- state-over-secret cookie precedence;
- exact conversation-title mismatch blocking a send;
- exactly-one-new-message verification;
- artifact/run continuity-gap detection;
- state persistence after each verified send;
- partial failure preserving the latest state; and
- local bootstrap subprocess calls receiving secrets through standard input.

Workflow structure tests cover:

- removal of `actions/cache`;
- artifact discovery and newest-unexpired selection;
- read-only workflow permissions;
- a non-cancelling concurrency group;
- fail-closed decrypt and validation;
- final encryption and upload on partial failure;
- plaintext cleanup;
- 90-day encrypted artifact retention; and
- manual `validate_only` wiring.

End-to-end verification requires two consecutive `validate_only=true` runs.
Both must load the friend list and send zero messages; the second must restore
the artifact created by the first.

## Success Criteria

- The Mac can be powered off during scheduled execution.
- Two consecutive validation-only runs succeed on different GitHub-hosted
  runners.
- The second validation restores encrypted runtime state from the first.
- No cookie or encryption key appears in logs or artifacts as plaintext.
- A normal retry or manual rerun does not send twice to a target already
  recorded for that date.
- Any uncertain identity or send state results in a skip, never a guessed
  send.
