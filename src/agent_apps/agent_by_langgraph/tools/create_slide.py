from pathlib import Path

from langchain_core.tools import tool

from agent_apps.agent_by_langgraph.utils.slide_kit import build_slide


@tool
def create_slide(title: str, key_points: list[str], recommendation: str) -> str:
    """Create a one-slide PowerPoint in the Voltway Research house style, saved as fleet.pptx."""
    sandbox = Path(__file__).resolve().parents[1] / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    build_slide(title, key_points, recommendation, str(sandbox / "fleet.pptx"))
    return "Saved the slide to /fleet.pptx"
