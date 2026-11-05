"""Expense MCP server: real user-supplied USD expenses, no model dependency.
📘 LEARN: FastMCP publishes function names, docstrings and type hints as tool schemas.
The client discovers/calls them via tools/list and tools/call over stdio.
⚠ PITFALL: stdout carries JSON-RPC; send logs to stderr.
The adapter may start a fresh process per call, so SQLite persists the ledger. Transactions
protect concurrent writes. Only trusted configuration selects the database path.

支出 MCP 服务：处理用户提供的真实美元支出，不依赖模型。
📘 LEARN：FastMCP 将函数名、文档字符串和类型提示发布为工具 schema。
客户端通过 stdio 上的 tools/list 和 tools/call 发现并调用工具。
⚠ PITFALL：stdout 传输 JSON-RPC，日志必须写 stderr。
适配器可能每次调用启动新进程，因此账本保存在 SQLite 中；事务保护并发写入。
数据库路径只由可信启动配置决定。
"""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

Category = Literal["餐饮", "交通", "购物", "居住", "娱乐", "其他"]
CATEGORIES = ("餐饮", "交通", "购物", "居住", "娱乐", "其他")
DB_PATH = Path(
    os.getenv(
        "LEDGER_DB",
        Path(__file__).resolve().parent.parent / "data" / "standalone-expenses.sqlite",
    )
)
mcp = FastMCP("expenses", log_level="WARNING")


@contextmanager
def _connect():
    """Use a short-lived connection; commit or roll back, then close it.

    每次操作使用短连接；事务提交或回滚后关闭连接。
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute("""CREATE TABLE IF NOT EXISTS expenses (
                id TEXT PRIMARY KEY,
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                spent_on TEXT NOT NULL,
                category TEXT NOT NULL,
                note TEXT NOT NULL
            )""")
            yield db
    finally:
        db.close()


def _cents(amount: str) -> int:
    # 📘 LEARN: store money as integer cents; validate decimal strings before conversion.
    # Reject non-finite numbers, negatives, scientific notation and excess decimal places.
    # 📘 LEARN：金额用整数美分存储，转换前先校验十进制字符串。
    # 拒绝非有限数字、负数、科学计数法和超过两位的小数。
    if not re.fullmatch(r"(?:0|[1-9]\d{0,7})(?:\.\d{1,2})?", amount):
        raise ValueError(
            "金额必须是 0.01 至 99999999.99 美元的十进制字符串，最多两位小数"
        )
    cents = int(Decimal(amount) * 100)
    if cents <= 0:
        raise ValueError("支出金额必须大于零")
    return cents


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _date(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("日期必须使用 YYYY-MM-DD 格式")
    return date.fromisoformat(value).isoformat()


def _category(value: str) -> str:
    if value not in CATEGORIES:
        raise ValueError(f"分类必须是以下之一：{', '.join(CATEGORIES)}")
    return value


def _note(value: str) -> str:
    if len(value) > 80:
        raise ValueError("备注最多 80 个字符")
    return value


def _id(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{12}", value):
        raise ValueError("记录 ID 必须是工具返回的 12 位小写十六进制字符串")
    return value


def _record(row) -> dict:
    return {
        "id": row["id"],
        "amount": _money(row["amount_cents"]),
        "spent_on": row["spent_on"],
        "category": row["category"],
        "note": row["note"],
    }


def _filters(start_date, end_date, category):
    clauses, params = [], []
    if start_date is not None:
        clauses.append("spent_on >= ?")
        params.append(_date(start_date))
    if end_date is not None:
        clauses.append("spent_on <= ?")
        params.append(_date(end_date))
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("开始日期不能晚于结束日期")
    if category is not None:
        clauses.append("category = ?")
        params.append(_category(category))

    # ⚠ PITFALL: SQL structure is code-controlled; model-provided values use parameter binding.
    # ⚠ PITFALL：SQL 结构由代码控制，模型提供的值通过参数绑定传入。
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


@mcp.tool()
def add_expense(amount: str, spent_on: str, category: Category, note: str = "") -> dict:
    """Add a real USD expense; requires human approval. amount is a decimal string such as "28.50";
    spent_on is YYYY-MM-DD. category must be 餐饮 (food), 交通 (transport), 购物 (shopping),
    居住 (housing), 娱乐 (entertainment), or 其他 (other). note is at most 80 characters.
    Return the saved record/ID; do not repeat a successful write.

    新增一笔真实美元支出，需人工审批。amount 为金额字符串，例如 "28.50"；
    spent_on 为 YYYY-MM-DD；分类为餐饮、交通、购物、居住、娱乐或其他。
    备注最多 80 个字符。返回实际保存的记录和 ID，成功后不要重复写入。
    """
    values = (
        uuid.uuid4().hex[:12],
        _cents(amount),
        _date(spent_on),
        _category(category),
        _note(note),
    )
    with _connect() as db:
        db.execute("INSERT INTO expenses VALUES (?, ?, ?, ?, ?)", values)
        row = db.execute("SELECT * FROM expenses WHERE id = ?", (values[0],)).fetchone()
    return {"currency": "USD", "expense": _record(row)}


@mcp.tool()
def list_expenses(
    start_date: str | None = None,
    end_date: str | None = None,
    category: Category | None = None,
    offset: int = 0,
    limit: int = 5,
) -> dict:
    """List matching USD expenses with inclusive date bounds; omitted dates are unbounded.
    Use 1–5 records per page and zero-based offset. Follow next_offset until null.
    total_count covers ALL matches; use summarize_expenses for totals, not just this page.

    分页查询美元支出，日期边界均包含当天，省略日期表示不限。
    每页 1–5 条，offset 从 0 开始；按 next_offset 翻页，直到其为 null。
    total_count 是全部匹配笔数；金额统计请用 summarize_expenses，不能只加总本页。
    """
    if offset < 0 or not 1 <= limit <= 5:
        raise ValueError("offset 必须 >= 0，limit 必须在 1 到 5 之间")
    where, params = _filters(start_date, end_date, category)
    with _connect() as db:
        # Read count and page from the same snapshot.
        # 从同一份快照读取笔数与分页数据。
        db.execute("BEGIN")
        count = db.execute("SELECT COUNT(*) FROM expenses" + where, params).fetchone()[
            0
        ]
        rows = db.execute(
            "SELECT * FROM expenses"
            + where
            + " ORDER BY spent_on, id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    next_offset = offset + len(rows)
    return {
        "currency": "USD",
        "total_count": count,
        "expenses": [_record(row) for row in rows],
        "next_offset": next_offset if next_offset < count else None,
    }


@mcp.tool()
def update_expense(
    expense_id: str,
    amount: str | None = None,
    spent_on: str | None = None,
    category: Category | None = None,
    note: str | None = None,
) -> dict:
    """Update a real expense ID with human approval. Only supply changed fields; omitted/null
    fields keep their values. amount is a USD decimal string, spent_on is YYYY-MM-DD.
    An empty note clears it. Query first and ask the user if multiple records fit; never guess IDs.

    按真实 ID 修改支出，需人工审批。只提供变更字段，省略或 null 表示保留原值。
    amount 是美元金额字符串，spent_on 是 YYYY-MM-DD，空字符串备注用于清空备注。
    先查询，多条匹配时询问用户；不能猜测 ID。
    """
    expense_id = _id(expense_id)
    changes = {}
    for column, value, validate in (
        ("amount_cents", amount, _cents),
        ("spent_on", spent_on, _date),
        ("category", category, _category),
        ("note", note, _note),
    ):
        if value is not None:
            changes[column] = validate(value)
    if not changes:
        raise ValueError("至少提供一个需要修改的字段")
    assignments = ", ".join(f"{column} = ?" for column in changes)
    with _connect() as db:
        result = db.execute(
            f"UPDATE expenses SET {assignments} WHERE id = ?",
            [*changes.values(), expense_id],
        )
        if result.rowcount == 0:
            raise ValueError(f"找不到记录：{expense_id}")
        row = db.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
    return {"currency": "USD", "expense": _record(row)}


@mcp.tool()
def delete_expense(expense_id: str) -> dict:
    """Delete an expense by its real ID with human approval. Query first if unsure; missing IDs fail.

    按真实 ID 删除支出，需人工审批。不确定时先查询；记录不存在时返回错误。
    """
    expense_id = _id(expense_id)
    with _connect() as db:
        result = db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        if result.rowcount == 0:
            raise ValueError(f"找不到记录：{expense_id}")
    return {"deleted_id": expense_id}


@mcp.tool()
def summarize_expenses(
    start_date: str | None = None,
    end_date: str | None = None,
    category: Category | None = None,
) -> dict:
    """Sum ALL matching USD expenses and group by category, independent of pagination.
    Dates use YYYY-MM-DD and include both endpoints; omitted dates are unbounded.
    Empty results have total="0.00", count=0. Send category/overall totals to calculate_share;
    if the overall total is zero, no percentage is defined.

    汇总全部匹配的美元支出并按分类分组，不受分页影响。
    日期为 YYYY-MM-DD，包含起止日；省略日期表示不限。
    空结果返回 total="0.00"、count=0；把分类合计和总额交给 calculate_share。
    总额为零时占比无定义。
    """
    where, params = _filters(start_date, end_date, category)
    with _connect() as db:
        rows = db.execute(
            "SELECT category, COUNT(*) AS count, SUM(amount_cents) AS cents FROM expenses"
            + where
            + " GROUP BY category ORDER BY category",
            params,
        ).fetchall()
    return {
        "currency": "USD",
        "start_date": start_date,
        "end_date": end_date,
        "category": category,
        "count": sum(row["count"] for row in rows),
        "total": _money(sum(row["cents"] for row in rows)),
        "by_category": [
            {
                "category": row["category"],
                "count": row["count"],
                "total": _money(row["cents"]),
            }
            for row in rows
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
