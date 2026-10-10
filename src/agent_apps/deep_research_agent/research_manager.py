import asyncio

from agents import Runner, gen_trace_id, trace

from .config import PROVIDER
from .sub_agents.email_agent import email_agent
from .sub_agents.planner_agent import WebSearchItem, WebSearchPlan, planner_agent
from .sub_agents.search_agent import search_agent
from .sub_agents.writer_agent import ReportData, writer_agent


class ResearchManager:
    async def run(self, query: str):
        """Run the deep research process, yielding the status updates and the final report"""
        if PROVIDER != "openai":
            raise ValueError(
                "The current WebSearchTool requires the OpenAI Responses API. "
                "Set PROVIDER=openai, OPENAI_MODEL and OPENAI_API_KEY in the root .env, "
                "or replace WebSearchTool with a search function tool for Ollama/OpenRouter."
            )
        trace_id = gen_trace_id()
        with trace("Research trace", trace_id=trace_id):
            yield f"Starting research. Trace: https://platform.openai.com/traces/trace?trace_id={trace_id}"
            search_plan = await self._plan_searches(query)
            yield f"Searches planned, starting {len(search_plan.searches)} searches..."
            search_results = await self._perform_searches(search_plan)
            yield "Searches complete, writing report..."
            report = await self._write_report(query, search_results)
            yield report.markdown_report + "\n\n---\nSending notification..."
            try:
                await self._send_email(report)
            except Exception:
                yield (
                    report.markdown_report
                    + "\n\n---\nResearch complete. Notification failed; "
                    "your report is preserved above. Check your notification settings."
                )
            else:
                yield (
                    report.markdown_report
                    + "\n\n---\nResearch complete. Notification sent."
                )

    async def _plan_searches(self, query: str) -> WebSearchPlan:
        """Plan the searches to perform for the query"""
        result = await Runner.run(planner_agent, f"Query: {query}")
        return result.final_output

    async def _perform_searches(self, search_plan: WebSearchPlan) -> list[str]:
        """Perform the searches to perform for the query"""
        tasks = [self._search(item) for item in search_plan.searches]
        return await asyncio.gather(*tasks)

    async def _search(self, item: WebSearchItem) -> str | None:
        """Perform a search for the query"""
        input_message = (
            f"Search term: {item.query}\nReason for searching: {item.reason}"
        )
        result = await Runner.run(search_agent, input_message)
        return result.final_output

    async def _write_report(self, query: str, search_results: list[str]) -> ReportData:
        """Write the report for the query"""
        input_message = (
            f"Original query: {query}\nSummarized search results: {search_results}"
        )
        result = await Runner.run(writer_agent, input_message)
        return result.final_output

    async def _send_email(self, report: ReportData) -> None:
        await Runner.run(email_agent, report.markdown_report)
