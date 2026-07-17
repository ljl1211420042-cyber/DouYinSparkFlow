import unittest
from unittest.mock import patch
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

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


class TimeoutLocator(FakeLocator):
    def wait_for(self, state, timeout):
        raise PlaywrightTimeoutError("friend list timeout")


class VisibleLocator(FakeLocator):
    def count(self):
        return 1

    def is_visible(self):
        return True


class RecoveringFriendLocator(FakeLocator):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.wait_timeouts = []

    def wait_for(self, state, timeout):
        self.wait_timeouts.append(timeout)
        if not self.page.reloaded:
            raise PlaywrightTimeoutError("friend list temporarily empty")
        super().wait_for(state, timeout)


class RecoveringEmptyFriendListPage:
    def __init__(self):
        self.reloaded = False
        self.reload_calls = 0
        self.friend = RecoveringFriendLocator(self)
        self.friend_tab = VisibleLocator()

    def locator(self, selector):
        if selector in tasks.AUTHENTICATION_PAGE_MARKERS:
            return MarkerLocator(False)
        if selector == tasks.EMPTY_FRIEND_LIST_SELECTOR:
            return MarkerLocator(not self.reloaded)
        if selector in tasks.FRIENDS_TAB_SELECTORS:
            return self.friend_tab
        return self.friend

    def reload(self, wait_until, timeout):
        self.reload_calls += 1
        self.reloaded = True


class FakePage:
    def __init__(self, friend=None):
        self.friend = friend or FakeLocator()
        self.selector = None

    def locator(self, selector):
        if selector in tasks.AUTHENTICATION_PAGE_MARKERS:
            return MarkerLocator(False)
        if selector == tasks.EMPTY_FRIEND_LIST_SELECTOR:
            return MarkerLocator(False)
        self.selector = selector
        return self.friend


class FakeNavigationPage:
    def goto(self, url):
        self.url = url


class FakeContext:
    def __init__(self, page, refreshed_cookies):
        self.page = page
        self.refreshed_cookies = refreshed_cookies
        self.closed = False
        self.added_cookies = None

    def set_default_navigation_timeout(self, timeout):
        self.navigation_timeout = timeout

    def set_default_timeout(self, timeout):
        self.default_timeout = timeout

    def new_page(self):
        return self.page

    def add_cookies(self, cookies):
        self.added_cookies = cookies

    def cookies(self):
        return self.refreshed_cookies

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, context=None):
        self.context = context
        self.closed = False

    def new_context(self):
        return self.context

    def close(self):
        self.closed = True


class FakePlaywright:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class WaitAndActivateFriendListTests(unittest.TestCase):
    def test_uses_current_conversation_list_selectors(self):
        self.assertIn("item-header-name-", tasks.CONVERSATION_ITEM_SELECTOR)
        self.assertIn("ReactVirtualized__Grid", tasks.CONVERSATION_SCROLL_SELECTOR)
        self.assertIn("normalize-space", tasks.CONVERSATION_SCROLL_SELECTOR)

    def test_all_missing_targets_fail_the_account_task(self):
        with self.assertRaisesRegex(RuntimeError, "2 个目标"):
            tasks.handle_missing_targets(
                "tester", {"one", "two"}, selected_count=0
            )

    def test_partial_missing_targets_only_warn(self):
        result = tasks.handle_missing_targets(
            "tester", {"one", "two"}, selected_count=1
        )

        self.assertEqual(result, 2)

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

    def test_friend_list_timeout_fails_the_account_task(self):
        page = FakePage(friend=TimeoutLocator())
        original_config = tasks.config
        tasks.config = {"browserTimeout": 1234}
        try:
            with patch.object(tasks, "save_page_diagnostics") as diagnostics:
                with self.assertRaisesRegex(RuntimeError, "好友列表"):
                    tasks.wait_and_activate_friend_list(
                        page, "tester", "friend-selector"
                    )
        finally:
            tasks.config = original_config

        diagnostics.assert_called_once_with(
            page, "tester", "friend_list_not_ready"
        )

    def test_empty_friend_list_reloads_once_before_sending(self):
        page = RecoveringEmptyFriendListPage()
        original_config = tasks.config
        tasks.config = {"browserTimeout": 20000}
        try:
            result = tasks.wait_and_activate_friend_list(
                page, "tester", "friend-selector"
            )
        finally:
            tasks.config = original_config

        self.assertTrue(result)
        self.assertEqual(page.reload_calls, 1)
        self.assertTrue(page.friend_tab.clicked)
        self.assertTrue(page.friend.clicked)
        self.assertEqual(page.friend.wait_timeouts, [15000, 5000])


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


class PresentButHiddenLocator(MarkerLocator):
    def count(self):
        return 1


class PresentButHiddenPage:
    def locator(self, selector):
        return PresentButHiddenLocator(False)


class FriendListEndMarkerTests(unittest.TestCase):
    def test_hidden_no_more_marker_does_not_end_search(self):
        page = PresentButHiddenPage()

        self.assertFalse(
            tasks.has_reached_friend_list_end(page, "no-more-selector")
        )

    def test_visible_no_more_marker_ends_search(self):
        page = MarkerPage({"no-more-selector"})

        self.assertTrue(
            tasks.has_reached_friend_list_end(page, "no-more-selector")
        )


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


class RefreshedCookieStateTests(unittest.TestCase):
    def setUp(self):
        self.original_config = tasks.config
        self.original_user_data = tasks.userData

    def tearDown(self):
        tasks.config = self.original_config
        tasks.userData = self.original_user_data

    def test_validation_only_returns_refreshed_cookies_without_sending(self):
        refreshed = [
            {
                "name": "sessionid",
                "value": "rotated",
                "domain": ".douyin.com",
                "path": "/",
            }
        ]
        context = FakeContext(
            page=FakeNavigationPage(), refreshed_cookies=refreshed
        )
        browser = FakeBrowser(context)
        tasks.config = {
            **self.original_config,
            "browserTimeout": 1234,
            "taskRetryTimes": 1,
            "validateOnly": True,
        }

        with patch.object(tasks, "retry_operation"):
            with patch.object(tasks, "validate_account_session") as validate:
                with patch.object(tasks, "scroll_and_select_user") as sender:
                    result = tasks.do_user_task(
                        browser,
                        "tester",
                        [{"name": "old"}],
                        ["target"],
                    )

        self.assertEqual(result, refreshed)
        validate.assert_called_once_with(context.page, "tester")
        sender.assert_not_called()
        self.assertTrue(context.closed)

    def test_complete_run_writes_refreshed_cookie_state(self):
        refreshed = [
            {
                "name": "sessionid",
                "value": "rotated",
                "domain": ".douyin.com",
                "path": "/",
            }
        ]
        browser = FakeBrowser()
        playwright = FakePlaywright()
        tasks.userData = [
            {
                "unique_id": "123",
                "username": "tester",
                "cookies": [],
                "targets": [],
            }
        ]

        with patch.dict(
            tasks.os.environ,
            {"COOKIE_STATE_OUTPUT": "/tmp/refreshed-state.json"},
            clear=False,
        ):
            with patch.object(tasks, "get_browser", return_value=(playwright, browser)):
                with patch.object(tasks, "do_user_task", return_value=refreshed):
                    with patch.object(tasks, "write_cookie_state") as write_state:
                        tasks.runTasks()

        write_state.assert_called_once_with(
            "/tmp/refreshed-state.json", {"COOKIES_123": refreshed}
        )
        self.assertTrue(browser.closed)
        self.assertTrue(playwright.stopped)

    def test_failed_run_does_not_write_cookie_state(self):
        browser = FakeBrowser()
        playwright = FakePlaywright()
        tasks.userData = [
            {
                "unique_id": "123",
                "username": "tester",
                "cookies": [],
                "targets": [],
            }
        ]

        with patch.dict(
            tasks.os.environ,
            {"COOKIE_STATE_OUTPUT": "/tmp/refreshed-state.json"},
            clear=False,
        ):
            with patch.object(tasks, "get_browser", return_value=(playwright, browser)):
                with patch.object(
                    tasks, "do_user_task", side_effect=RuntimeError("failed")
                ):
                    with patch.object(tasks, "write_cookie_state") as write_state:
                        with self.assertRaisesRegex(RuntimeError, "failed"):
                            tasks.runTasks()

        write_state.assert_not_called()
        self.assertTrue(browser.closed)
        self.assertTrue(playwright.stopped)

if __name__ == "__main__":
    unittest.main()
