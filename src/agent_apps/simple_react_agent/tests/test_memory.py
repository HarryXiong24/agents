"""检查学习计划的三个字段、列表保存、更新、并行写入与跨进程读取。"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_apps.simple_react_agent import memory


@pytest.fixture(autouse=True)
def isolate_plans(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "PLANS_FILE", tmp_path / "data" / "study_plans.json")


def test_first_start_does_not_create_file():
    assert memory.load_plans() == []
    assert not memory.PLANS_FILE.parent.exists()


def test_save_multiple_plans_and_update_only_same_project_date():
    first = memory.save_plan(" Python ", 60, "2026-10-29")
    second = memory.save_plan("英语", 30, "2026-10-29")
    third = memory.save_plan("Python", 45, "2026-10-30")
    assert first == {"project": "Python", "minutes": 60, "date": "2026-10-29"}
    assert memory.load_plans() == [first, second, third]
    updated = memory.save_plan("Python", 90, "2026-10-29")
    assert memory.load_plans() == [updated, second, third]
    assert json.loads(memory.PLANS_FILE.read_text(encoding="utf-8")) == [updated, second, third]
    assert all(set(plan) == {"project", "minutes", "date"} for plan in memory.load_plans())


@pytest.mark.parametrize("deleted", [False, True])
def test_new_process_reads_saved_plans(deleted):
    saved = memory.save_plan("Python", 60, "2026-10-29")
    if deleted:
        assert memory.delete_plan("Python", "2026-10-29")
    # 新进程没有本轮消息或全局缓存，只能从磁盘读取这份计划。
    result = subprocess.run(
        [sys.executable, "-c", (
            "import json, sys; from pathlib import Path; "
            "from agent_apps.simple_react_agent import memory; "
            "memory.PLANS_FILE = Path(sys.argv[1]); "
            "print(json.dumps(memory.load_plans()))"
        ), str(memory.PLANS_FILE)],
        check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == ([] if deleted else [saved])


@pytest.mark.parametrize(("field", "value", "error"), [
    ("project", " ", ValueError), ("project", 123, TypeError),
    ("minutes", 0, ValueError), ("minutes", -1, ValueError), ("minutes", 1441, ValueError),
    ("minutes", 30.5, TypeError), ("minutes", "30", TypeError), ("minutes", True, TypeError),
    ("date", "2026-02-30", ValueError), ("date", "20261029", ValueError),
    ("date", "2026-W44-4", ValueError), ("date", "2026-2-3", ValueError),
    ("date", "", ValueError), ("date", 20261029, TypeError),
])
def test_invalid_save_keeps_existing_plans(field, value, error):
    saved = memory.save_plan("Python", 60, "2026-10-29")
    args = {"project": "英语", "minutes": 30, "date": "2026-10-30"}
    args[field] = value
    with pytest.raises(error):
        memory.save_plan(args["project"], args["minutes"], args["date"])
    assert memory.load_plans() == [saved]


@pytest.mark.parametrize(("text", "error"), [
    ("损坏的 JSON", ValueError), ("{}", TypeError), ("[30]", TypeError),
    ('[{"project": "Python", "minutes": 30}]', ValueError),
    ('[{"project": "Python", "minutes": 30, "date": "2026-10-29", "note": "多余字段"}]', ValueError),
    ('[{"project": "Python", "minutes": true, "date": "2026-10-29"}]', TypeError),
    ('[{"project": "Python", "minutes": 30, "date": "2026-02-30"}]', ValueError),
])
def test_invalid_file_is_not_overwritten(text, error):
    memory.PLANS_FILE.parent.mkdir(parents=True)
    memory.PLANS_FILE.write_text(text, encoding="utf-8")
    with pytest.raises(error):
        memory.load_plans()
    with pytest.raises(error):
        memory.save_plan("英语", 30, "2026-10-29")
    with pytest.raises(error):
        memory.delete_plan("英语", "2026-10-29")
    assert memory.PLANS_FILE.read_text(encoding="utf-8") == text


def test_concurrent_saves_keep_every_plan():
    with ThreadPoolExecutor(max_workers=4) as pool:
        saved = list(pool.map(lambda index: memory.save_plan(f"项目{index}", 30, "2026-10-29"), range(12)))
    assert sorted(memory.load_plans(), key=lambda plan: plan["project"]) == sorted(saved, key=lambda plan: plan["project"])


@pytest.mark.parametrize("operation", ["save", "delete"])
def test_failed_replace_preserves_file_and_removes_temporary_file(monkeypatch, operation):
    saved = memory.save_plan("Python", 60, "2026-10-29")

    def fail_replace(self, target):
        raise OSError("测试中的文件替换失败")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="替换失败"):
        if operation == "save":
            memory.save_plan("英语", 30, "2026-10-29")
        else:
            memory.delete_plan("Python", "2026-10-29")
    assert memory.load_plans() == [saved]
    assert list(memory.PLANS_FILE.parent.iterdir()) == [memory.PLANS_FILE]


def test_delete_only_matches_both_project_and_date():
    memory.save_plan("Python", 60, "2026-10-29")
    same_project = memory.save_plan("Python", 45, "2026-10-30")
    same_date = memory.save_plan("英语", 30, "2026-10-29")
    assert memory.delete_plan(" Python ", "2026-10-29") is True
    assert memory.load_plans() == [same_project, same_date]
    before = memory.PLANS_FILE.read_bytes()
    assert memory.delete_plan("Python", "2026-10-29") is False
    assert memory.PLANS_FILE.read_bytes() == before


def test_delete_missing_plan_does_not_create_file():
    assert memory.delete_plan("Python", "2026-10-29") is False
    assert not memory.PLANS_FILE.parent.exists()


@pytest.mark.parametrize(("project", "planned_date", "error"), [
    (" ", "2026-10-29", ValueError), (None, "2026-10-29", TypeError),
    ("Python", "2026-02-30", ValueError), ("Python", "20261029", ValueError),
    ("Python", None, TypeError),
])
def test_invalid_delete_preserves_plans(project, planned_date, error):
    saved = memory.save_plan("Python", 60, "2026-10-29")
    with pytest.raises(error):
        memory.delete_plan(project, planned_date)
    assert memory.load_plans() == [saved]


def test_save_and_delete_share_the_same_lock():
    memory.save_plan("Python", 60, "2026-10-29")
    with ThreadPoolExecutor(max_workers=2) as pool:
        saved = pool.submit(memory.save_plan, "英语", 30, "2026-10-29")
        deleted = pool.submit(memory.delete_plan, "Python", "2026-10-29")
        saved_plan = saved.result()
        assert deleted.result() is True
        assert memory.load_plans() == [saved_plan]
