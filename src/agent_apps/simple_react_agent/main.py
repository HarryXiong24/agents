"""学习路线：创建模型 → 定义两个节点 → 连线 → 在终端循环对话。

本文件使用同步调用，便于沿执行顺序阅读。会话历史只保存在内存里。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from .tools import TOOLS


SYSTEM_PROMPT = """你是学习时间小助手，始终使用中文，简短、清楚地回答。
你可以陪用户讨论学习安排，也可以使用工具获取当前时间、计算学习时长。
涉及数值运算时使用计算器；询问当前时间时使用时间工具。
需要多步计算时，先调用工具得到结果，再根据结果继续调用工具，最后回答。
注意分钟与小时的换算，一小时等于六十分钟。普通交流直接回答即可。
工具返回错误时，检查参数；无法继续时向用户说明，不要编造结果。
你只能参考本次对话历史，不要声称能在程序重启后记住信息。
"""


def create_model() -> BaseChatModel:
    """第一块积木：读取项目根目录的配置，创建聊天模型。"""
    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("请在项目根目录的 .env 中设置 GROQ_API_KEY。")

    return ChatGroq(
        model=os.getenv("AGENT_MODEL") or "openai/gpt-oss-20b",
        api_key=api_key,
        base_url=os.getenv("GROQ_BASE_URL") or "https://api.groq.com",
        temperature=0,
        timeout=30,
        max_retries=1,
    )


def build_graph(model: BaseChatModel):
    """第三块积木：只用模型节点和工具节点，搭建 ReAct 循环。"""
    # 绑定工具说明，让模型知道有哪些工具和参数；这一步不会执行工具。
    model_with_tools = model.bind_tools(TOOLS)

    def call_model(state: MessagesState):
        # 系统提示词只随请求发送，不反复追加到历史中。
        response = model_with_tools.invoke(
            [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        )
        # MessagesState 会合并消息：新 ID 追加，相同 ID 替换。
        return {"messages": [response]}

    def route_after_model(state: MessagesState):
        # 模型提出工具调用就去执行，否则本轮回答完成。
        if state["messages"][-1].tool_calls:
            return "tools"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_node(
        "tools",
        ToolNode(TOOLS, handle_tool_errors="工具执行失败，请检查参数后重试，或向用户说明。"),
    )

    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route_after_model, ["tools", END])
    graph.add_edge("tools", "model")
    # 没有检查点：完整历史由下面的终端循环显式保存和传入。
    return graph.compile()


def chat(graph) -> None:
    """第四块积木：接收输入，运行一轮，再保存完整消息历史。"""
    messages = []
    print("学习时间小助手已启动。输入“退出”结束；本次对话仅保存在内存中。")

    while True:
        try:
            text = input("你：").strip()
            if text == "退出":
                break
            if not text:
                continue

            # 每次都传入完整历史，再加上本次用户输入。
            # 简单限制图的执行步数，避免模型反复调用工具；步数不等于工具调用次数。
            result = graph.invoke(
                {"messages": [*messages, HumanMessage(text)]},
                config={"recursion_limit": 20},
            )
            # 用图返回的完整历史替换本地列表，不能再把整个结果追加一遍。
            # 只有本轮成功后才更新，失败的半轮消息不会混入下一次对话。
            messages = result["messages"]
            print(f"助手：{messages[-1].text}\n")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except GraphRecursionError:
            print("助手：本轮工具调用步骤过多，请缩小问题范围后重试。\n")
        except Exception as exc:
            print(f"助手：本轮执行失败，请检查网络、模型配置或输入后重试。详情：{exc}\n")

    print("助手：再见！")


def main() -> None:
    """把模型、图和终端对话连接起来。"""
    try:
        graph = build_graph(create_model())
    except Exception as exc:
        raise SystemExit(f"启动失败：{exc}") from exc
    chat(graph)
