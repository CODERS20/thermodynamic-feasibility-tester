"""Save the local API key using a hidden terminal prompt."""

import getpass
import os
import tempfile

from website.openai_config import CONFIG_PATH


def save_key(key, path=CONFIG_PATH):
    key = key.strip()
    if len(key) < 20 or not key.startswith("sk-") or any(char.isspace() for char in key):
        raise ValueError("Enter the full OpenAI API key beginning with sk-.")
    file_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            file_name = handle.name
            handle.write(f"OPENAI_API_KEY={key}\nOPENAI_MODEL=gpt-4o-mini\n")
        os.replace(file_name, path)
    finally:
        if file_name and os.path.exists(file_name):
            os.unlink(file_name)


if __name__ == "__main__":
    try:
        save_key(getpass.getpass("Paste your OpenAI API key (hidden): "))
        print("Saved local OpenAI settings. Restart python website/serve.py to enable AI extraction.")
    except (ValueError, OSError) as error:
        print(f"Configuration failed: {error}")
        raise SystemExit(1)
