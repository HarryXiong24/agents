"""Launch Ledger with `uv run bookkeeping-agent` or `python -m agent_apps.bookkeeping_agent`.

通过 uv run bookkeeping-agent 或 python -m agent_apps.bookkeeping_agent 启动 Ledger。
"""

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
