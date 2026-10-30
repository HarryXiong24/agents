"""学习路线：创建模型 → 定义两个节点 → 连线 → 在终端循环对话。

本文件使用同步调用，便于沿执行顺序阅读。会话历史保存在内存里，学习计划保存在文件里。
"""

import readline

from groq import APIError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from . import memory
from .model import create_model
from .prompts import TOOL_ERROR_MESSAGE, build_system_prompt
from .tools import TOOLS


def build_graph(model: BaseChatModel):
    """第三块积木：只用模型节点和工具节点，搭建 ReAct 循环。"""
    # 绑定工具说明，让模型知道有哪些工具和参数；这一步不会执行工具。
    model_with_tools = model.bind_tools(TOOLS)

    # 节点函数：返回状态更新。
    def call_model(state: MessagesState):
        # 第二版新增：每次调用模型前读取全部计划，工具刚保存的计划也能立即使用。
        # 文件只负责保存；这里把计划加入提示词，模型才能看到并参考它。
        plans = memory.load_plans()
        system = build_system_prompt(plans)
        # 系统提示词只随请求发送，不反复追加到历史中。
        response = model_with_tools.invoke([SystemMessage(system), *state["messages"]])
        # MessagesState 会合并消息：新 ID 追加，相同 ID 替换。
        return {"messages": [response]}

    # 条件路由函数：返回下一节点的名称。
    def route_after_model(state: MessagesState):
        # 模型提出工具调用就去执行，否则本轮回答完成。
        if state["messages"][-1].tool_calls:
            return "tools"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_node(
        "tools",
        ToolNode(TOOLS, handle_tool_errors=TOOL_ERROR_MESSAGE),
    )

    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route_after_model, ["tools", END])
    graph.add_edge("tools", "model")

    # 没有检查点：完整历史由下面的终端循环显式保存和传入。
    return graph.compile()


def chat(graph) -> None:
    """第四块积木：接收输入，运行一轮，再保存完整消息历史。"""
    # 导入 readline 后，input() 会按完整字符编辑中文，避免退格只删除部分 UTF-8 字节。
    # 关闭自动输入历史，仍然只由下面的 messages 列表管理对话。
    readline.set_auto_history(False)
    messages = []
    print(
        "学习时间小助手已启动。输入“退出”结束；对话保存在内存中，学习计划可保存到文件。"
    )

    while True:
        try:
            print("------")
            text = input("输入：").strip()
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
        except APIError as exc:
            print(
                f"助手：本轮执行失败，请检查网络、密钥或模型配置后重试。详情：{exc}\n"
            )
        # 处理文件读写错误，以及计划读取时明确抛出的值错误和类型错误。
        # 未列出的异常继续抛出，保留错误堆栈供排查。
        except (OSError, ValueError, TypeError) as exc:
            print(f"助手：本轮执行失败，请检查学习计划文件或输入后重试。详情：{exc}\n")

    print("助手：再见！")


def main() -> None:
    """把模型、图和终端对话连接起来。"""
    try:
        model = create_model()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"启动失败：{exc}") from exc
    # 图的构建错误直接抛出，避免把节点或连线问题误当作模型配置错误。
    graph = build_graph(model)
    chat(graph)
