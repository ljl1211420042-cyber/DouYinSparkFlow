import unittest
from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/schedule.yml")


class CookieStateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_manual_dispatch_exposes_validation_only_mode(self):
        self.assertIn("validate_only:", self.workflow)
        self.assertIn("type: boolean", self.workflow)
        self.assertIn("VALIDATE_ONLY:", self.workflow)
        self.assertIn("inputs.validate_only", self.workflow)

    def test_restores_encrypted_cookie_state_cache(self):
        self.assertIn("uses: actions/cache@v4", self.workflow)
        self.assertIn("path: .cookie-state/state.enc", self.workflow)
        self.assertIn(
            "key: douyin-cookie-state-${{ github.run_id }}", self.workflow
        )
        self.assertIn("restore-keys: |", self.workflow)
        self.assertIn("douyin-cookie-state-", self.workflow)

    def test_decrypts_cached_state_with_fallback(self):
        self.assertIn("COOKIE_STATE_KEY: ${{ secrets.COOKIE_STATE_KEY }}", self.workflow)
        self.assertIn(
            "openssl enc -d -aes-256-cbc -pbkdf2", self.workflow
        )
        self.assertIn("COOKIE_STATE_FILE=", self.workflow)
        self.assertIn("using bootstrap Cookie Secret", self.workflow)

    def test_encrypts_only_refreshed_state_and_removes_plaintext(self):
        self.assertIn(
            "COOKIE_STATE_OUTPUT: .cookie-state/refreshed.json", self.workflow
        )
        self.assertIn("if: ${{ success() }}", self.workflow)
        self.assertIn("openssl enc -aes-256-cbc -pbkdf2", self.workflow)
        self.assertIn("-salt", self.workflow)
        self.assertIn(
            "rm -f .cookie-state/latest.json .cookie-state/refreshed.json",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
