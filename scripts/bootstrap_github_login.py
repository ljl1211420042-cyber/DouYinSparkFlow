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
CREATOR_HOME_PREFIX = "https://creator.douyin.com/creator-micro/home"
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


def return_to_chat_after_login(page):
    """QR login redirects to home; resume the chat-page verification."""
    if not isinstance(page.url, str):
        return False
    if not page.url.startswith(CREATOR_HOME_PREFIX):
        return False
    page.goto(CHAT_URL, wait_until="domcontentloaded")
    return True


def capture_logged_in_cookies(timeout_seconds):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(CHAT_URL)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            return_to_chat_after_login(page)
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
