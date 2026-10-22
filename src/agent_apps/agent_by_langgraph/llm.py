from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_groq import ChatGroq

from agent_apps.agent_by_langgraph.models.company import Company
from agent_apps.agent_by_langgraph.tools.get_share_price import get_share_price

from .utils.chat_model import create_model


def llm():
    model = create_model()

    # Invoke the LLM with a message and print the reply
    # message = "In 1 sentence, what does it mean for an AI Agent to be autonomous"
    # invoked_reply = invoke(llm, message)
    # print("Invoked reply:", invoked_reply)

    # stream(llm, message)

    # Convert messages to dicts and invoke the LLM
    # message_to_dict(llm)

    # Demonstrate the LLM's ability to handle structured tool calls
    model = model.bind_tools([get_share_price])

    messages = [HumanMessage("What is the share price of Amazon?")]
    response = model.invoke(messages)
    print("content:", response, "tool_calls:", response.tool_calls)
    messages.append(response)

    for tool_call in response.tool_calls:
        if tool_call["name"] == "get_share_price":
            result = get_share_price.invoke(tool_call["args"])
            messages.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )

    final = model.invoke(messages)
    print(final.content)

    # Demonstrate the LLM's ability to handle structured output
    model = create_model().with_structured_output(Company, method="function_calling")
    company = model.invoke("Tell me about Amazon the technology company")
    print(company)


def invoke(model: ChatGroq, message: str) -> str:
    reply = model.invoke(message)
    return reply.content


def stream(model: ChatGroq, message: str):
    print("Streaming reply:")
    for chunk in model.stream(message):
        print(chunk.content, end="", flush=True)


def message_to_dict(model: ChatGroq) -> dict:
    messages = [
        SystemMessage("You are a terse assistant who answers in exactly five words."),
        HumanMessage("What is the capital of France?"),
    ]

    print(model.invoke(messages).content)

    # The exact same call using plain dictionaries, the format you already know
    messages_as_dicts = [
        {
            "role": "system",
            "content": "You are a terse assistant who answers in exactly five words.",
        },
        {"role": "user", "content": "What is the capital of France?"},
    ]
    print(model.invoke(messages_as_dicts).content)
