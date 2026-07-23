import subprocess
import unittest
from unittest.mock import Mock, patch

from scripts.bootstrap_github_login import (
    CHAT_URL,
    capture_logged_in_cookies,
    return_to_chat_after_login,
    set_environment_secret,
)


class BootstrapSecretTests(unittest.TestCase):
    def test_redirects_from_creator_home_back_to_chat_after_qr_login(self):
        page = Mock()
        page.url = "https://creator.douyin.com/creator-micro/home"

        self.assertTrue(return_to_chat_after_login(page))
        page.goto.assert_called_once_with(
            CHAT_URL,
            wait_until="domcontentloaded",
        )

    def test_does_not_interrupt_external_login_redirect(self):
        page = Mock()
        page.url = "https://sso.douyin.com/login"

        self.assertFalse(return_to_chat_after_login(page))
        page.goto.assert_not_called()

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
        playwright = sync_playwright.return_value.__enter__.return_value
        browser = playwright.chromium.launch.return_value
        login_page = browser.new_context.return_value.new_page.return_value
        login_page.locator.return_value.count.return_value = 0
        with self.assertRaisesRegex(RuntimeError, "扫码登录超时"):
            capture_logged_in_cookies(1)


if __name__ == "__main__":
    unittest.main()
