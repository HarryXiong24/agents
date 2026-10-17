from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

from agent_apps.agent_by_langgraph.middlewares.log_agent_end import log_agent_end
from agent_apps.agent_by_langgraph.middlewares.log_agent_start import log_agent_start
from agent_apps.agent_by_langgraph.middlewares.log_model_request import (
    log_model_request,
)
from agent_apps.agent_by_langgraph.middlewares.log_model_response import (
    log_model_response,
)
from agent_apps.agent_by_langgraph.middlewares.log_tool_calls import log_tool_calls
from agent_apps.agent_by_langgraph.middlewares.time_model_calls import time_model_calls
from agent_apps.agent_by_langgraph.models.city_report import CityReport
from agent_apps.agent_by_langgraph.tools.get_population import get_population
from agent_apps.agent_by_langgraph.tools.get_weather import get_weather
from agent_apps.agent_by_langgraph.utils.print_graph import print_graph


def agent():
    agent = create_agent(
        model="ollama:gpt-oss:20b",
        tools=[get_weather, get_population],
        system_prompt="You are a travel assistant. Use your tools to answer questions about cities.",
        checkpointer=MemorySaver(),
        response_format=CityReport,
        middleware=[
            log_agent_start,
            log_agent_end,
            log_model_request,
            log_model_response,
            time_model_calls,
            log_tool_calls,
        ],
    )
    print_graph(agent.get_graph())

    # Async version
    # result = await agent.ainvoke()

    config = {"configurable": {"thread_id": "trip-planning"}}

    # Invoke the agent with a user message
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "I am planning a trip to London."}]},
        config=config,
    )
    print("------ First Round ------")
    print(result["messages"][-1].content)

    # Invoke the agent with a user message asking for weather and population
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "What is my planned trip and what is the weather and population for my planned trip?",
                }
            ]
        },
        config=config,
    )
    print("------ Second Round ------")
    print(result["messages"][-1].content)
    report = result["structured_response"]
    print("Report: ", report)
