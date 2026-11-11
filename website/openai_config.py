"""Load local OpenAI settings outside the served website directory."""

import os
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / ".env.local"


def load_config(path=CONFIG_PATH):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name in {"OPENAI_API_KEY", "OPENAI_MODEL"} and value.strip():
            os.environ.setdefault(name, value.strip())

