import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=True)

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

# All examples in this package use Groq, independently of other apps' PROVIDER.
AGENT_MODEL = os.getenv("AGENT_MODEL") or "openai/gpt-oss-20b"
# The Groq SDK appends /openai/v1 to this host itself.
BASE_URL = os.getenv("GROQ_BASE_URL") or "https://api.groq.com"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError(f"Set GROQ_API_KEY in {PROJECT_ROOT / '.env'}.")

DEEP_AGENT_RECURSION_LIMIT = int(os.getenv("DEEP_AGENT_RECURSION_LIMIT", "20"))
