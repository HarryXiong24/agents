"""Configuration: which provider to talk to, which model, and file locations.

Every provider listed here speaks the same OpenAI chat-completions protocol,
so one client class reaches all of them - only the URL, the key and the model
id change. That is why adding a provider is a new entry in PROVIDERS rather
than a new code path in agent.py.

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

# One entry per provider you can talk to:
#   base_url      - its OpenAI-compatible endpoint
#   api_key_env   - the .env variable holding its key; "" means no key needed
#   model_env     - the .env variable naming the model to use
#   default_model - used when model_env is not set
#
# The variable names are spelled out rather than built from the provider name
# (PROVIDER.upper() + "_MODEL"), because the two spellings drift: the key here
# is "openrouter" but the .env variables read OPEN_ROUTER_*. Writing them out
# keeps this table the single place where a name is decided.
PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPEN_ROUTER_API_KEY",
        "model_env": "OPEN_ROUTER_MODEL",
        "default_model": "openai/gpt-oss-20b:free",
    },
    "ollama": {
        # Ollama serves an OpenAI-compatible API on /v1 next to its own one.
        # It runs on your machine, so there is no key and nothing to pay.
        # Its model ids are local names like "gemma4:cloud" - a hosted id such
        # as "openai/gpt-oss-20b:free" means nothing here and returns a 404.
        "base_url": "http://localhost:11434/v1",
        "api_key_env": "",
        "model_env": "OLLAMA_MODEL",
        "default_model": "gemma4:cloud",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-5.4-mini",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1/",
        "api_key_env": "ANTHROPIC_API_KEY",
        "model_env": "ANTHROPIC_MODEL",
        "default_model": "claude-sonnet-4-6",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GOOGLE_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-3-flash",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model_env": "DEEPSEEK_MODEL",
        "default_model": "deepseek-chat",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "default_model": "llama-3.3-70b-versatile",
    },
    "grok": {
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "GROK_API_KEY",
        "model_env": "GROK_MODEL",
        "default_model": "grok-4",
    },
}

# Which one to use. Set PROVIDER=ollama in .env to switch the whole agent over.
PROVIDER = os.getenv("PROVIDER", "openrouter").strip().lower()

# Fail here, with the list of valid names, rather than later with a confusing
# connection error from a provider that does not exist.
if PROVIDER not in PROVIDERS:
    raise ValueError(
        f"Unknown PROVIDER {PROVIDER!r}. Choose one of: {', '.join(PROVIDERS)}."
    )

_SETTINGS = PROVIDERS[PROVIDER]

# Where to send requests.
BASE_URL = _SETTINGS["base_url"]

# The name of the key variable, kept so the agent can say which one is missing.
API_KEY_ENV = _SETTINGS["api_key_env"]

# The key itself. Empty string if it is not set - Agent checks it and explains.
# Providers that need no key get a placeholder, because the OpenAI client
# refuses to start without something in this field.
API_KEY = os.getenv(API_KEY_ENV, "") if API_KEY_ENV else "not-needed"

# Whether a real key is required, so the agent knows an empty one is a problem.
REQUIRES_API_KEY = bool(API_KEY_ENV)

# The name of the model variable, so errors can point at the right line.
MODEL_ENV = _SETTINGS["model_env"]

# Which model to talk to. Each provider reads its own variable, which is what
# makes switching back and forth painless: one shared MODEL would send an
# OpenRouter model id to Ollama the moment you flipped PROVIDER.
MODEL = os.getenv(MODEL_ENV) or _SETTINGS["default_model"]

# The profile files that tell the agent who it is representing.
# These are Path objects, so they carry methods like .read_text() and .open().
LINKEDIN_PATH = BASE_DIR / "assets" / "linkedin.pdf"
SUMMARY_PATH = BASE_DIR / "assets" / "summary.txt"

# Where visitor email addresses collected by the tool are appended.
EMAILS_PATH = BASE_DIR / "assets" / "emails.txt"
