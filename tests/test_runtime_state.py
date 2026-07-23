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
