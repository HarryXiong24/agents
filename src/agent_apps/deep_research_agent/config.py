import os
from pathlib import Path

from agents import OpenAIChatCompletionsModel, OpenAIResponsesModel
from dotenv import load_dotenv
from openai import AsyncOpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=True)

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

_client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
_model_type = (
    OpenAIResponsesModel if PROVIDER == "openai" else OpenAIChatCompletionsModel
)
MODEL = _model_type(model=MODEL_NAME, openai_client=_client)

HOW_MANY_SEARCHES = int(os.getenv("HOW_MANY_SEARCHES", "5"))
if HOW_MANY_SEARCHES < 1:
    raise ValueError("HOW_MANY_SEARCHES must be at least 1.")
USE_EMAIL = os.getenv("USE_EMAIL", "true").strip().lower() == "true"
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
PUSHOVER_USER = os.getenv("PUSHOVER_USER")
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN")
