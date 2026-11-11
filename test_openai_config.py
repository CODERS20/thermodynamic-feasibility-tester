import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from configure_openai import save_key
from website.openai_config import load_config


class OpenAIConfigTests(unittest.TestCase):
    def test_local_configuration_roundtrip_and_environment_precedence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            path = Path(folder) / ".env.local"
            save_key("sk-unit-test-placeholder-key", path)
            with patch("website.openai_config.os.environ", {}):
                load_config(path)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "sk-unit-test-placeholder-key")
                self.assertEqual(os.environ["OPENAI_MODEL"], "gpt-4o-mini")
                os.environ["OPENAI_API_KEY"] = "existing-key"
                load_config(path)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "existing-key")
            with self.assertRaises(ValueError):
                save_key("invalid", path)
            self.assertIn("sk-unit-test-placeholder-key", path.read_text())


if __name__ == "__main__":
    unittest.main()
