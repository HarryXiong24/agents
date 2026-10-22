import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from agent_apps.agent_by_langgraph.tools.search import search


class SearchToolTests(unittest.TestCase):
    def setUp(self):
        self.wrapper_patch = patch(
            "agent_apps.agent_by_langgraph.tools.search.GoogleSerperAPIWrapper"
        )
        self.wrapper = self.wrapper_patch.start()
        self.addCleanup(self.wrapper_patch.stop)
        self.wrapper.return_value.run.return_value = "Search results"

    def test_valid_query_uses_fixed_result_limit(self):
        self.assertEqual(search.invoke({"query": "Tesla Model Y"}), "Search results")
        self.wrapper.assert_called_once_with(k=3)
        self.wrapper.return_value.run.assert_called_once_with("Tesla Model Y")

    def test_invalid_arguments_do_not_reach_search_api(self):
        for args in (
            {"query": "Tesla Model Y", "max_results": 3},
            {"query": "Tesla Model Y", "unexpected": True},
            {},
            {"query": ""},
            {"query": 123},
        ):
            with self.subTest(args=args):
                result = search.invoke(args)
                self.assertIn("Invalid search arguments", result)
                self.assertIn("Retry with only", result)
        self.wrapper.assert_not_called()

    def test_tool_node_returns_error_then_accepts_corrected_call(self):
        builder = StateGraph(MessagesState)
        builder.add_node("tools", ToolNode([search]))
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        graph = builder.compile()
        invalid = AIMessage(
            content="",
            tool_calls=[{
                "name": "search",
                "args": {"query": "Tesla Model Y", "max_results": 3},
                "id": "bad-search",
            }],
        )
        error = graph.invoke({"messages": [invalid]})["messages"][-1]
        self.assertEqual(error.status, "error")
        self.assertEqual(error.tool_call_id, "bad-search")
        self.wrapper.assert_not_called()

        corrected = AIMessage(
            content="",
            tool_calls=[{
                "name": "search",
                "args": {"query": "Tesla Model Y"},
                "id": "corrected-search",
            }],
        )
        result = graph.invoke({"messages": [invalid, error, corrected]})["messages"][-1]
        self.assertEqual(result.status, "success")
        self.assertEqual(result.content, "Search results")

    def test_api_failures_are_not_hidden_as_argument_errors(self):
        self.wrapper.return_value.run.side_effect = RuntimeError("Search API unavailable")
        with self.assertRaisesRegex(RuntimeError, "Search API unavailable"):
            search.invoke({"query": "Tesla Model Y"})


if __name__ == "__main__":
    unittest.main()
