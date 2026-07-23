import unittest
from unittest.mock import patch

from utils import config as config_module


class ValidateOnlyConfigTests(unittest.TestCase):
    def test_reads_validate_only_true(self):
        original = config_module.config
        config_module.config = None
        try:
            with patch.dict(
                config_module.os.environ,
                {"VALIDATE_ONLY": "true"},
                clear=False,
            ):
                self.assertTrue(config_module.get_config()["validateOnly"])
        finally:
            config_module.config = original

    def test_validate_only_defaults_to_false(self):
        original = config_module.config
        config_module.config = None
        try:
            with patch.dict(config_module.os.environ, {}, clear=True):
                self.assertFalse(config_module.get_config()["validateOnly"])
        finally:
            config_module.config = original

    def test_message_send_interval_defaults_to_eight_seconds(self):
        original = config_module.config
        config_module.config = None
        try:
            with patch.dict(config_module.os.environ, {}, clear=True):
                self.assertEqual(
                    config_module.get_config()["messageSendIntervalSeconds"],
                    8.0,
                )
        finally:
            config_module.config = original

    def test_reads_message_send_interval(self):
        original = config_module.config
        config_module.config = None
        try:
            with patch.dict(
                config_module.os.environ,
                {"MESSAGE_SEND_INTERVAL_SECONDS": "12.5"},
                clear=False,
            ):
                self.assertEqual(
                    config_module.get_config()["messageSendIntervalSeconds"],
                    12.5,
                )
        finally:
            config_module.config = original

    def test_reads_runtime_state_paths(self):
        original = config_module.config
        config_module.config = None
        try:
            with patch.dict(
                config_module.os.environ,
                {
                    "RUNTIME_STATE_FILE": "/tmp/input.json",
                    "RUNTIME_STATE_OUTPUT": "/tmp/output.json",
                    "RUNTIME_STATE_UNCERTAIN_MARKER": "/tmp/uncertain",
                    "LEDGER_TIMEZONE": "Asia/Shanghai",
                },
                clear=False,
            ):
                config = config_module.get_config()
                self.assertEqual(config["runtimeStateFile"], "/tmp/input.json")
                self.assertEqual(config["runtimeStateOutput"], "/tmp/output.json")
                self.assertEqual(
                    config["runtimeStateUncertainMarker"],
                    "/tmp/uncertain",
                )
                self.assertEqual(config["ledgerTimezone"], "Asia/Shanghai")
        finally:
            config_module.config = original


if __name__ == "__main__":
    unittest.main()
