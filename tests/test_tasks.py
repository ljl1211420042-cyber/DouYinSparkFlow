import unittest
from unittest.mock import patch

from core import tasks


class FakeLocator:
    def __init__(self):
        self.waited = False
        self.clicked = False

    @property
    def first(self):
        return self

    def wait_for(self, state, timeout):
        self.waited = (state, timeout)

    def click(self):
        self.clicked = True


class FakePage:
    def __init__(self):
        self.friend = FakeLocator()
        self.selector = None

    def locator(self, selector):
        if selector in tasks.AUTHENTICATION_PAGE_MARKERS:
            return MarkerLocator(False)
        self.selector = selector
        return self.friend


class WaitAndActivateFriendListTests(unittest.TestCase):
    def test_uses_playwright_first_locator_property(self):
        page = FakePage()
        original_config = tasks.config
        tasks.config = {"browserTimeout": 1234}
        try:
            result = tasks.wait_and_activate_friend_list(page, "tester", "friend-selector")
        finally:
            tasks.config = original_config

        self.assertTrue(result)
        self.assertEqual(page.selector, "friend-selector")
        self.assertEqual(page.friend.waited, ("visible", 1234))
        self.assertTrue(page.friend.clicked)


class MarkerLocator:
    def __init__(self, visible=False):
        self.visible = visible

    def count(self):
        return 1 if self.visible else 0

    def is_visible(self):
        return self.visible

    @property
    def first(self):
        return self


class MarkerPage:
    def __init__(self, visible_selectors):
        self.visible_selectors = set(visible_selectors)

    def locator(self, selector):
        return MarkerLocator(selector in self.visible_selectors)


class DelayedAuthenticationPage(MarkerPage):
    def __init__(self):
        super().__init__(set())

    def wait_for_timeout(self, timeout):
        self.visible_selectors.update(tasks.AUTHENTICATION_PAGE_MARKERS)


class AuthenticationPageTests(unittest.TestCase):
    def test_detects_creator_center_login_page(self):
        page = MarkerPage({"text=扫码登录", "text=登录/注册"})

        self.assertTrue(tasks.is_authentication_page(page))

    def test_detects_login_when_only_one_login_marker_is_visible(self):
        page = MarkerPage({"text=扫码登录"})

        self.assertTrue(tasks.is_authentication_page(page))

    def test_friend_list_wait_fails_fast_and_saves_diagnostics(self):
        page = MarkerPage({"text=扫码登录", "text=登录/注册"})

        with patch.object(tasks, "save_page_diagnostics") as diagnostics:
            with self.assertRaisesRegex(RuntimeError, "Cookie"):
                tasks.wait_and_activate_friend_list(
                    page, "tester", "friend-selector"
                )

        diagnostics.assert_called_once_with(
            page, "tester", "authentication_required"
        )

    def test_friend_list_search_checks_authentication_before_tab_wait(self):
        page = MarkerPage({"text=扫码登录", "text=登录/注册"})

        with patch.object(tasks, "save_page_diagnostics") as diagnostics:
            with self.assertRaisesRegex(RuntimeError, "Cookie"):
                next(tasks.scroll_and_select_user(page, "tester", ["target"]))

        diagnostics.assert_called_once_with(
            page, "tester", "authentication_required"
        )

    def test_friend_list_search_detects_login_page_that_renders_late(self):
        page = DelayedAuthenticationPage()
        original_config = tasks.config
        tasks.config = {**original_config, "browserTimeout": 1000}
        try:
            with patch.object(tasks, "save_page_diagnostics") as diagnostics:
                with self.assertRaisesRegex(RuntimeError, "Cookie"):
                    next(
                        tasks.scroll_and_select_user(
                            page, "tester", ["target"]
                        )
                    )
        finally:
            tasks.config = original_config

        diagnostics.assert_called_once_with(
            page, "tester", "authentication_required"
        )


if __name__ == "__main__":
    unittest.main()
