"""训练计划存储：支持当前计划 + 备选方案 + 待确认计划。

持久化：data/plans.json
结构：
{
  "activeId": "plan-xxx",
  "pending": null | {...},
  "plans": [
    {"id": "plan-xxx", "name": "...", "goal": "...", "content": "markdown",
     "days": [...], "createdAt": "...", "updatedAt": "..."}
  ]
}
"""
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from . import config

_PLANS_FILE = config.CONFIG.MEMORY_DIR / "plans.json"

# plans.json 的每个公开函数都是「读文件 → 改 → 写回」，无锁时并发请求
# （如同时应用两个计划）会互相覆盖。用 RLock 而非 Lock：apply_pending 在
# 持锁期间会调 active_plan()，后者也要拿锁，RLock 允许同线程重入。
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _load() -> dict:
    if not _PLANS_FILE.exists():
        return {"activeId": None, "pending": None, "plans": []}
    try:
        data = json.loads(_PLANS_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {"activeId": None, "pending": None, "plans": []}
    data.setdefault("activeId", None)
    data.setdefault("pending", None)
    data.setdefault("plans", [])
    return data


def _save(data: dict) -> None:
    config.CONFIG.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _PLANS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_plans() -> dict:
    """返回完整计划库（含 activeId、pending、plans）。"""
    with _LOCK:
        return _load()


def active_plan() -> Optional[dict]:
    with _LOCK:
        data = _load()
        active_id = data.get("activeId")
        if not active_id:
            return None
        for p in data.get("plans", []):
            if p.get("id") == active_id:
                return p
        return None


def set_pending(plan: dict) -> dict:
    """把一份待确认计划写入 plans.json 的 pending 字段。"""
    with _LOCK:
        data = _load()
        plan["id"] = plan.get("id") or f"pending-{uuid.uuid4().hex[:8]}"
        plan.setdefault("createdAt", _now())
        plan.setdefault("updatedAt", _now())
        data["pending"] = plan
        _save(data)
        return plan


def apply_pending(action: str) -> dict:
    """将 pending 计划应用为 replace（替换当前计划）或 add（新增备选方案）。

    返回 {"ok": bool, "msg": str, "active": plan|null}
    """
    with _LOCK:
        data = _load()
        pending = data.get("pending")
        if not pending:
            return {"ok": False, "msg": "没有待确认的计划", "active": active_plan()}

        now = _now()
        pending["updatedAt"] = now

        if action == "replace":
            # 替换当前激活计划：如果有 activeId 则更新同名计划，否则新建并激活
            active_id = data.get("activeId")
            replaced = False
            for i, p in enumerate(data.get("plans", [])):
                if p.get("id") == active_id:
                    pending["id"] = active_id
                    data["plans"][i] = pending
                    replaced = True
                    break
            if not replaced:
                pending["id"] = pending.get("id") or f"plan-{uuid.uuid4().hex[:8]}"
                data["plans"].append(pending)
                data["activeId"] = pending["id"]
            data["pending"] = None
            _save(data)
            return {"ok": True, "msg": f"已用「{pending.get('name')}」替换当前计划", "active": pending}

        if action == "add":
            # 作为备选方案加入，保留旧计划为 active，新计划加入列表
            pending["id"] = f"plan-{uuid.uuid4().hex[:8]}"
            data.setdefault("plans", []).append(pending)
            # 若当前没有 active，则把新方案设为 active
            if not data.get("activeId"):
                data["activeId"] = pending["id"]
            data["pending"] = None
            _save(data)
            return {"ok": True, "msg": f"已把「{pending.get('name')}」加入为备选方案（方案二）", "active": active_plan()}

        return {"ok": False, "msg": f"不支持的 action：{action}（仅支持 replace / add）", "active": active_plan()}


def switch_plan(plan_id: str) -> dict:
    """切换到指定计划为当前 active。"""
    with _LOCK:
        data = _load()
        ids = {p.get("id") for p in data.get("plans", [])}
        if plan_id not in ids:
            return {"ok": False, "msg": "未找到该计划", "active": active_plan()}
        data["activeId"] = plan_id
        _save(data)
        p = next((x for x in data["plans"] if x["id"] == plan_id), None)
        return {"ok": True, "msg": f"已切换到「{p.get('name')}」", "active": p}


def delete_plan(plan_id: str) -> dict:
    """删除指定计划。若删除的是当前 active 计划，自动提升剩余第一个为激活（无剩余则置空）。"""
    with _LOCK:
        data = _load()
        before = len(data.get("plans", []))
        data["plans"] = [p for p in data.get("plans", []) if p.get("id") != plan_id]
        if len(data["plans"]) == before:
            return {"ok": False, "msg": "未找到该计划"}
        # 若删掉的是当前激活计划：提升剩余第一个为激活，没有则置空
        if data.get("activeId") == plan_id:
            data["activeId"] = data["plans"][0]["id"] if data.get("plans") else None
        _save(data)
        return {"ok": True, "msg": "已删除计划"}


def clear_pending() -> dict:
    """放弃当前待确认计划（不改变已保存的计划）。"""
    with _LOCK:
        data = _load()
        data["pending"] = None
        _save(data)
        return {"ok": True, "msg": "已放弃待确认计划"}


def save_plan(plan: dict, activate: bool = False) -> dict:
    """直接保存一份计划（用于外部导入或程序化写入）。"""
    with _LOCK:
        data = _load()
        plan.setdefault("id", f"plan-{uuid.uuid4().hex[:8]}")
        plan.setdefault("createdAt", _now())
        plan.setdefault("updatedAt", _now())
        existing = False
        for i, p in enumerate(data.get("plans", [])):
            if p.get("id") == plan["id"]:
                data["plans"][i] = plan
                existing = True
                break
        if not existing:
            data["plans"].append(plan)
        if activate or not data.get("activeId"):
            data["activeId"] = plan["id"]
        _save(data)
        return {"ok": True, "plan": plan}
