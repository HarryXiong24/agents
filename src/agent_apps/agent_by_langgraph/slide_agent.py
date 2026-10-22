from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from agent_apps.agent_by_langgraph.tools.create_slide import create_slide

from .utils.chat_model import create_model


def slide_agent():
    sandbox = Path(__file__).resolve().parent / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    model = create_model()

    slide_maker = {
        "name": "slide-maker",
        "description": "Turns a finished recommendation into a one-slide PowerPoint deck.",
        "system_prompt": "You turn research recommendations into slides, following your fleet-slide skill.",
        "tools": [create_slide],
        "skills": ["/skills/"],
    }

    presenter = create_deep_agent(
        model=model,
        subagents=[slide_maker],
        system_prompt="You prepare research for presentation by delegating to your slide-maker sub-agent.",
        backend=FilesystemBackend(root_dir=sandbox, virtual_mode=True),
    )

    result = presenter.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Read fleet.md and have a one-slide deck made of its recommendation.",
                }
            ]
        }
    )
    print(result["messages"][-1].content)
