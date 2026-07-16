import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from utils.cookie_state import (
    cookie_key,
    load_cookie_state,
    normalize_cookies,
    validate_cookie_state,
    write_cookie_state,
)


class CookieStateTests(unittest.TestCase):
    def test_normalizes_supported_playwright_fields(self):
        cookies = normalize_cookies(
            [
                {
                    "name": "sessionid",
                    "value": "secret",
                    "domain": ".douyin.com",
                    "path": "/",
                    "expires": 1234567890,
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                    "storeId": "0",
                    "unexpected": "discarded",
                }
            ]
        )

        self.assertEqual(
            cookies,
            [
                {
                    "name": "sessionid",
                    "value": "secret",
                    "domain": ".douyin.com",
                    "path": "/",
                    "expires": 1234567890,
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                }
            ],
        )

    def test_rejects_invalid_state_key(self):
        with self.assertRaisesRegex(ValueError, "COOKIES_"):
            validate_cookie_state({"OTHER_SECRET": []})

    def test_rejects_cookie_without_required_fields(self):
        with self.assertRaisesRegex(ValueError, "required"):
            validate_cookie_state(
                {
                    "COOKIES_123": [
                        {"name": "sessionid", "domain": ".douyin.com"}
                    ]
                }
            )

    def test_round_trips_state_with_owner_only_permissions(self):
        state = {
            cookie_key("123"): [
                {
                    "name": "sessionid",
                    "value": "secret",
                    "domain": ".douyin.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nested" / "state.json"
            write_cookie_state(path, state)

            self.assertEqual(load_cookie_state(path), state)
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), state
            )


if __name__ == "__main__":
    unittest.main()
