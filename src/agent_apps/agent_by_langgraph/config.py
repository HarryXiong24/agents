import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=True)

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

# Local deep-agent defaults for short development runs.
DEEP_AGENT_MODEL = os.getenv("DEEP_AGENT_MODEL", "gpt-oss:20b")
DEEP_AGENT_NUM_CTX = int(os.getenv("DEEP_AGENT_NUM_CTX", "8192"))
DEEP_AGENT_NUM_PREDICT = int(os.getenv("DEEP_AGENT_NUM_PREDICT", "1024"))
DEEP_AGENT_RECURSION_LIMIT = int(os.getenv("DEEP_AGENT_RECURSION_LIMIT", "20"))
DEEP_AGENT_REASONING = os.getenv("DEEP_AGENT_REASONING", "low")

PROVIDERS = {
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "prefix": "OLLAMA",
        "default_model": "gpt-oss:20b",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "prefix": "OPEN_ROUTER",
        "default_model": "openai/gpt-oss-20b:free",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "prefix": "OPENAI",
        "default_model": "gpt-5.4-mini",
    },
}

PROVIDER = os.getenv("PROVIDER", "openai").strip().lower()
if PROVIDER not in PROVIDERS:
    raise ValueError(f"Unsupported PROVIDER {PROVIDER!r}. Use {', '.join(PROVIDERS)}.")

_settings = PROVIDERS[PROVIDER]
_prefix = _settings["prefix"]
MODEL_NAME = os.getenv(f"{_prefix}_MODEL") or _settings["default_model"]
BASE_URL = os.getenv(f"{_prefix}_BASE_URL") or _settings["base_url"]
API_KEY = os.getenv(f"{_prefix}_API_KEY")
if PROVIDER == "ollama":
    API_KEY = API_KEY or "ollama"
elif not API_KEY:
    raise ValueError(f"Set {_prefix}_API_KEY in {PROJECT_ROOT / '.env'}.")
