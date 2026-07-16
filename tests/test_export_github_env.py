import json
import unittest

from utils.export_github_env import build_environment


class BuildEnvironmentTests(unittest.TestCase):
    def test_cached_cookie_state_overrides_matching_secret(self):
        result = build_environment(
            {"TASKS": [{"unique_id": "123"}]},
            {
                "COOKIES_123": "bootstrap-cookie",
                "COOKIES_456": "other-bootstrap-cookie",
                "OTHER_SECRET": "preserved",
            },
            {
                "COOKIES_123": [
                    {
                        "name": "sessionid",
                        "value": "refreshed",
                        "domain": ".douyin.com",
                        "path": "/",
                    }
                ]
            },
        )

        self.assertEqual(json.loads(result["COOKIES_123"])[0]["value"], "refreshed")
        self.assertEqual(result["COOKIES_456"], "other-bootstrap-cookie")
        self.assertEqual(result["OTHER_SECRET"], "preserved")
        self.assertEqual(json.loads(result["TASKS"])[0]["unique_id"], "123")

    def test_empty_state_keeps_bootstrap_cookie(self):
        result = build_environment(
            {}, {"COOKIES_123": "bootstrap-cookie"}, {}
        )

        self.assertEqual(result["COOKIES_123"], "bootstrap-cookie")

    def test_encryption_key_is_not_exported_to_runtime_environment(self):
        result = build_environment(
            {},
            {
                "COOKIE_STATE_KEY": "encryption-key",
                "COOKIES_123": "bootstrap-cookie",
            },
            {},
        )

        self.assertNotIn("COOKIE_STATE_KEY", result)
        self.assertEqual(result["COOKIES_123"], "bootstrap-cookie")


if __name__ == "__main__":
    unittest.main()
