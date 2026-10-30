"""第五块积木：用 JSON 列表保存学习计划，每条只有项目、分钟数、日期。"""

import json
from datetime import date as calendar_date
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import TypedDict

# 根据本文件的位置确定路径，从不同工作目录启动时也会读写同一个文件。
# 文件在首次保存时创建；只保存计划，不保存整段对话。
PLANS_FILE = Path(__file__).resolve().parent / "data" / "study_plans.json"
# 同一批工具调用可能并行执行，保存和删除共用锁，避免“读、改、写”相互覆盖。
_WRITE_LOCK = Lock()


class StudyPlan(TypedDict):
    """一条计划只有这三个字段；TypedDict 帮助阅读，实际校验由下面的函数执行。"""

    project: str
    minutes: int
    date: str


def _validate_plan_key(project: str, planned_date: str) -> tuple[str, str]:
    """项目和日期共同定位计划，读取、保存、删除共用校验。"""
    if not isinstance(project, str):
        raise TypeError("学习项目必须是字符串。")
    project = project.strip()
    if not project:
        raise ValueError("学习项目不能为空。")
    if not isinstance(planned_date, str):
        raise TypeError("学习日期必须是字符串。")
    try:
        parsed_date = calendar_date.fromisoformat(planned_date)
    except ValueError as exc:
        raise ValueError("学习日期必须是 YYYY-MM-DD 格式的真实日期。") from exc
    # fromisoformat 也接受某些其他 ISO 写法，这里统一要求年月日完整格式。
    if parsed_date.isoformat() != planned_date:
        raise ValueError("学习日期必须使用 YYYY-MM-DD 格式。")
    return project, planned_date


def _validate_plan(project: str, minutes: int, planned_date: str) -> StudyPlan:
    """类型错误用 TypeError，内容或范围错误用 ValueError。"""
    project, planned_date = _validate_plan_key(project, planned_date)
    if type(minutes) is not int:
        raise TypeError("学习时长必须是整数分钟。")
    if not 1 <= minutes <= 1440:
        raise ValueError("学习时长必须是 1 到 1440 之间的整数分钟。")
    return {"project": project, "minutes": minutes, "date": planned_date}


def load_plans() -> list[StudyPlan]:
    """读取全部学习计划；首次启动没有文件时返回空列表。"""
    if not PLANS_FILE.exists():
        return []
    try:
        plans = json.loads(PLANS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "学习计划文件不是有效的 JSON，请检查 study_plans.json。"
        ) from exc
    if not isinstance(plans, list):
        raise TypeError("学习计划文件必须是 JSON 数组。")

    validated = []
    for plan in plans:
        if not isinstance(plan, dict):
            raise TypeError("每条学习计划必须是 JSON 对象。")
        if set(plan) != {"project", "minutes", "date"}:
            raise ValueError(
                "每条学习计划必须且只能包含 project、minutes、date 三个字段。"
            )
        validated.append(_validate_plan(plan["project"], plan["minutes"], plan["date"]))
    return validated


def save_plan(project: str, minutes: int, planned_date: str) -> StudyPlan:
    """新增计划；同一项目、同一日期已经存在时更新时长，其他计划保留。"""
    plan = _validate_plan(project, minutes, planned_date)
    with _WRITE_LOCK:
        plans = load_plans()
        for index, existing in enumerate(plans):
            if (
                existing["project"] == plan["project"]
                and existing["date"] == plan["date"]
            ):
                plans[index] = plan
                break
        else:
            # for ... else：没有找到相同项目、日期时，添加一条新计划。
            plans.append(plan)

        _write_plans(plans)
    return plan


def delete_plan(project: str, planned_date: str) -> bool:
    """按项目和日期删除一条计划，成功返回 True，未找到返回 False。"""
    project, planned_date = _validate_plan_key(project, planned_date)
    with _WRITE_LOCK:
        plans = load_plans()
        for index, plan in enumerate(plans):
            if plan["project"] == project and plan["date"] == planned_date:
                del plans[index]
                # 其他项目或日期的计划保持原样；最后一条删除后写入空列表。
                _write_plans(plans)
                return True
    # 未找到时不写文件；首次使用时也不创建空文件。
    return False


def _write_plans(plans: list[StudyPlan]) -> None:
    """保存和删除共用的写文件步骤，由调用方持有写入锁。"""
    PLANS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 先写临时文件，写完后再替换正式文件，读取时就不会碰到半份 JSON。
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=PLANS_FILE.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(json.dumps(plans, ensure_ascii=False, indent=2) + "\n")
        # 退出 with 后文件已经关闭，再替换正式文件。
        temporary_path.replace(PLANS_FILE)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
