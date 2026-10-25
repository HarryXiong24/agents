"""Check real ledger persistence, money, filters and validation without an LLM.
无需真实模型，验证账本持久化、金额、筛选和输入校验。
"""

import asyncio
import json
from dataclasses import replace

import pytest

from agent_apps.react_agent.agent import mcp_client
from agent_apps.react_agent.agent.tools import calculate_share
from agent_apps.react_agent.mcp_servers import expense_server as ledger


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "DB_PATH", tmp_path / "expenses.sqlite")


def test_exact_money_filters_pagination_and_mutations():
    assert ledger.summarize_expenses()["total"] == "0.00"
    ids = [ledger.add_expense("0.10", "2026-10-25", "餐饮")["expense"]["id"] for _ in range(6)]
    ride = ledger.add_expense("0.20", "2026-10-26", "交通")["expense"]
    ledger.add_expense("100.00", "2026-09-01", "购物")
    result = ledger.summarize_expenses("2026-10-25", "2026-10-26")
    assert result["total"] == "0.80" and result["count"] == 7
    assert result["currency"] == "USD"
    assert ledger.summarize_expenses(category="餐饮")["total"] == "0.60"
    page = ledger.list_expenses("2026-10-25", "2026-10-26")
    assert page["total_count"] == 7 and page["next_offset"] == 5
    last = ledger.list_expenses("2026-10-25", "2026-10-26", offset=page["next_offset"])
    assert len(last["expenses"]) == 2 and last["next_offset"] is None
    assert len({item["id"] for item in page["expenses"] + last["expenses"]}) == 7
    assert ledger.list_expenses(offset=100)["expenses"] == []
    changed = ledger.update_expense(ride["id"], amount="0.30", note="Bus / 公交")["expense"]
    assert changed["spent_on"] == "2026-10-26" and changed["category"] == "交通"
    assert changed["amount"] == "0.30" and changed["note"] == "Bus / 公交"
    assert ledger.update_expense(ride["id"], note="")["expense"]["note"] == ""
    ledger.delete_expense(ids[0])
    assert ledger.summarize_expenses("2026-10-25", "2026-10-26")["total"] == "0.80"
    with pytest.raises(ValueError):
        ledger.delete_expense(ids[0])


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "0.001", "1e2", "100000000", "1; DROP TABLE expenses"])
def test_invalid_money_does_not_write(amount):
    with pytest.raises(ValueError):
        ledger.add_expense(amount, "2026-10-25", "餐饮")
    assert ledger.summarize_expenses()["count"] == 0


def test_invalid_fields_and_updates_leave_ledger_unchanged():
    for args in [("1", "2026-02-30", "餐饮"), ("1", "20261025", "餐饮"), ("1", "2026-10-25", "unknown")]:
        with pytest.raises(ValueError):
            ledger.add_expense(*args)
    with pytest.raises(ValueError):
        ledger.add_expense("1", "2026-10-25", "餐饮", "x" * 81)
    record = ledger.add_expense("10", "2026-10-25", "餐饮")["expense"]
    with pytest.raises(ValueError):
        ledger.update_expense(record["id"], amount="5", spent_on="bad-date")
    assert ledger.summarize_expenses()["total"] == "10.00"
    for record_id in ["../outside", "000000000000"]:
        with pytest.raises(ValueError):
            ledger.update_expense(record_id, amount="5")
    with pytest.raises(ValueError):
        ledger.update_expense(record["id"])
    with pytest.raises(ValueError):
        ledger.list_expenses(limit=6)
    with pytest.raises(ValueError):
        ledger.list_expenses(offset=-1)
    with pytest.raises(ValueError):
        ledger.summarize_expenses("2026-10-26", "2026-10-25")


@pytest.mark.parametrize("part,total", [("0", "0"), ("-1", "10"), ("11", "10"), ("NaN", "10"), ("1", "Infinity"), ("bad", "10")])
def test_invalid_shares(part, total):
    with pytest.raises(ValueError):
        calculate_share.invoke({"part": part, "total": total})


def test_share_rounding():
    assert calculate_share.invoke({"part": "0.10", "total": "0.30"}) == "33.33%"
    assert calculate_share.invoke({"part": "0", "total": "100"}) == "0.00%"


def test_real_mcp_sessions_persist_and_separate_users(tmp_path, monkeypatch):
    # Use real stdio sessions; each call may launch a new server process.
    # 使用真实 stdio 会话；每次调用都可能启动新服务进程。
    monkeypatch.setattr(mcp_client, "settings", replace(mcp_client.settings, mcp_config=mcp_client.ROOT / "mcp_servers.json"))
    monkeypatch.setattr(mcp_client, "user_data_dir", lambda user: tmp_path / user)

    async def call(tools, name, args):
        result = await tools[name].ainvoke(args)
        text = "\n".join(block["text"] for block in result if block.get("type") == "text")
        return json.loads(text)

    async def run():
        loaded, report = await mcp_client.load_mcp_tools(user_id="alice")
        assert len(report["expenses"]) == 5
        alice = {tool.name: tool for tool in loaded}
        result = await call(alice, "add_expense", {"amount": "12.34", "spent_on": "2026-10-25", "category": "餐饮"})
        record_id = result["expense"]["id"]
        assert (await call(alice, "summarize_expenses", {}))["total"] == "12.34"
        again, _ = await mcp_client.load_mcp_tools(user_id="alice")
        assert (await call({t.name: t for t in again}, "list_expenses", {}))["expenses"][0]["id"] == record_id
        loaded, _ = await mcp_client.load_mcp_tools(user_id="bob")
        assert (await call({t.name: t for t in loaded}, "summarize_expenses", {}))["count"] == 0
        await call(alice, "update_expense", {"expense_id": record_id, "amount": "10.20"})
        assert (await call(alice, "summarize_expenses", {}))["total"] == "10.20"
        await call(alice, "delete_expense", {"expense_id": record_id})
        assert (await call(alice, "summarize_expenses", {}))["total"] == "0.00"

    asyncio.run(run())
