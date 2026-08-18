"""Configuration: API key, model name and file locations.

Everything here is read once, when the module is first imported.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# This file's own folder. Anchoring to __file__ keeps the paths below correct
# whatever directory you start python from; "./assets/..." would not.
BASE_DIR = Path(__file__).resolve().parent

# The repo root: the nearest folder at or above this one that holds .env.
# Searching beats counting parents (BASE_DIR.parents[2]), which breaks silently
# when the package moves - you just get "API key is not set" and go hunting.
PROJECT_ROOT = next(
    (p for p in [BASE_DIR, *BASE_DIR.parents] if (p / ".env").is_file()), BASE_DIR
)

# Name the file explicitly: load_dotenv() with no argument searches from the
# current working directory. override=True lets .env win over the shell.
load_dotenv(PROJECT_ROOT / ".env", override=True)

# Your OpenRouter API key. Empty string if it is not set - ChatAgent checks it.
API_KEY = os.getenv("OPEN_ROUTER_API_KEY", "")

# Which model to talk to. Any OpenRouter model id works here.
MODEL = os.getenv("MODEL", "openai/gpt-oss-20b:free")

# The profile files that tell the agent who it is representing.
# These are Path objects, so they carry methods like .read_text() and .open().
LINKEDIN_PATH = BASE_DIR / "assets" / "linkedin.pdf"
SUMMARY_PATH = BASE_DIR / "assets" / "summary.txt"

# Where visitor email addresses collected by the tool are appended.
EMAILS_PATH = BASE_DIR / "assets" / "emails.txt"
