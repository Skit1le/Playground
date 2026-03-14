import re
import unittest

from app.config import Settings


class SettingsTestCase(unittest.TestCase):
    def test_allowed_origin_regex_accepts_localhost_and_loopback_dev_ports(self) -> None:
        settings = Settings(
            ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000",
            ALLOWED_ORIGIN_REGEX=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        )

        self.assertTrue(re.match(settings.allowed_origin_regex, "http://127.0.0.1:3004"))
        self.assertTrue(re.match(settings.allowed_origin_regex, "http://localhost:3999"))
        self.assertFalse(re.match(settings.allowed_origin_regex, "https://example.com"))


if __name__ == "__main__":
    unittest.main()
