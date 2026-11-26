"""Read application settings once and prepare an isolated Codex workspace."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
from pydantic import SecretStr

APP_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    model: str | None = None
    api_key: SecretStr | None = None
    tool_calls_per_turn: int = 8
    tool_history_limit: int = 10
    turn_timeout_seconds: float = 180
    draft_timeout_seconds: float = 60

    @property
    def codex_home(self) -> Path:
        return self.data_dir / "codex_home"

    @property
    def workspace(self) -> Path:
        return self.data_dir / "workspace"


def load_config() -> AppConfig:
    values = dotenv_values(APP_DIR / ".env", interpolate=False)
    api_key = values.get("OPENAI_API_KEY")
    return AppConfig(
        data_dir=APP_DIR / "data",
        model=values.get("CODEX_MODEL") or None,
        api_key=SecretStr(api_key) if api_key else None,
    )


def prepare_workspace(config: AppConfig) -> None:
    config.codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Codex discovers repo-scoped skills relative to the thread's working directory.
    shutil.copytree(
        APP_DIR / "skills",
        config.workspace / ".agents" / "skills",
        dirs_exist_ok=True,
    )
