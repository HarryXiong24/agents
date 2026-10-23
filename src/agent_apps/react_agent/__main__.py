"""Launch Atlas with `uv run react-agent` or `python -m agent_apps.react_agent`."""

import asyncio
import sys

from .main import main as run_console


def main() -> None:
    try:
        asyncio.run(run_console())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
