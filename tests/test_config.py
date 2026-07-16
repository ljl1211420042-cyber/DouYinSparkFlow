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


if __name__ == "__main__":
    unittest.main()
