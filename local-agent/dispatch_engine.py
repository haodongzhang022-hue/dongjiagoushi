# -*- coding: utf-8 -*-
"""
经理分配引擎（Dispatch Engine）
================================
实现「架构·经理」的**分发四层递进深度模型**（docs/DISPATCH_DEPTH.md）——
只声明是远远不够的，要的是接单后真正继续工作的完整闭环。

四层递进（由浅入深）：
  L1 声明：角色/任务被定义声明（issue 声明头 / settings.yml / team.yaml）
  L2 分发：经理拆分任务 + 分配角色 + 投功能域任务池（ops.enqueue_task）
  L3 触发：派发触发目标角色 + **等待接单回执**（[接单] 确认）
  L4 工作：**接单确认 → 开工 → 进度尺推进 → 向上交付**（最终目标）

只有走完 L1→L4 全链路（含接单回执 + 开工 + 进度尺 + 交付），
才算「经理真正把工作分配下去了」。

设计原则：
  - 每层都有可核验的留痕（数据库记录 + 平台 Issue + goal_meters 进度尺）；
  - 全局唯一 gid 稳定寻址：同一任务/agent 二次触发不漂移；
  - 每个任务分配独立 Issue（供被分配 agent 认领/开工）；
  - 触发消息写入消息管线，供后续接力消费；
  - L4 要求：接单回执 + 进度尺推进 + 交付留痕。
"""
import os
import subprocess
import sys

# 允许直接以脚本运行（python dispatch_engine.py）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data import admin
import ops

# 自动初始化数据库（幂等）
admin.init()


# ============================================================
# L1 声明：任务/角色的定义声明
# ============================================================
def _validate_assignment(assignment):
    """校验一个任务分配项的必填字段。"""
    required = ["task_key", "role", "domain"]
    missing = [k for k in required if not assignment.get(k)]
    if missing:
        raise ValueError(f"任务分配缺少必填字段: {missing}")


def declare_assignments(assignments):
    """
    L1 · 声明层。
    为每个任务登记全局唯一 gid（task + agent），确保声明在册。

    输入：任务分配清单 [{task_key, title, role, domain, ...}]
    输出：每个任务的声明记录
    """
    results = []
    for a in assignments:
        _validate_assignment(a)
        task = ops.register_task(a["task_key"], title=a.get("title", ""))
        results.append({
            "level": 1,
            "task_key": a["task_key"],
            "task_id": task["task_id"],
            "title": a.get("title", ""),
            "role": a["role"],
            "domain": a["domain"],
            "depends_on": a.get("depends_on", ""),
            "priority": a.get("priority", "P1"),
            "detail": a.get("detail", ""),
            "is_new": task["is_new"],
            "status": "declared",
        })
    return results


# ============================================================
# L2 分发：拆分任务 + 分配角色 + 投池 + 创建 Issue
# ============================================================
def _create_issue(repo, title, body):
    """调用 cnb CLI 创建独立 Issue（平台留痕）。返回 issue_number 或 None。"""
    if not repo:
        return None
    try:
        cmd = ["cnb", "issues", "create-issue",
               "--repo", repo, "--title", title, "--body", body]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if result.returncode == 0:
            import json
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict) and "data" in data:
                    return data["data"].get("number")
                if isinstance(data, dict):
                    return data.get("number")
            except json.JSONDecodeError:
                pass
            for line in result.stdout.splitlines():
                if "number" in line and ":" in line:
                    val = line.split(":", 1)[1].strip()
                    try:
                        return int(val)
                    except ValueError:
                        continue
        for line in result.stderr.splitlines():
            if "number" in line and ":" in line:
                val = line.split(":", 1)[1].strip()
                try:
                    return int(val)
                except ValueError:
                    continue
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def dispatch_assign(repo, assignments):
    """
    L2 · 分发层。
    对每个任务：拆分任务 + 分配 agent gid + 投入功能域池 + 创建独立 Issue。

    输入：任务分配清单 [{task_key, title, role, domain, ...}]
    输出：每个任务的分发记录
    """
    results = []
    for a in assignments:
        _validate_assignment(a)
        # ① 注册任务 gid（幂等，二次触发同一任务）
        task = ops.register_task(a["task_key"], title=a.get("title", ""))
        # ② 注册 agent gid（幂等，二次触发同一 agent）
        agent = ops.register_agent_for(a["task_key"], role=a.get("role", "架构·开发"))
        # ③ 投入功能域池
        pool = ops.enqueue_task(a["domain"], task["task_id"],
                                title=a.get("title", ""))
        # ④ 登记任务状态
        admin.assign_task(
            task["task_id"],
            title=a.get("title", ""),
            assignee=agent["agent_id"],
            depends_on=a.get("depends_on", ""),
            status="todo",
            detail={"role": a["role"], "domain": a["domain"],
                    "priority": a.get("priority", "P1"),
                    "depth_level": "L2·已分发"},
        )
        # ⑤ 创建独立 Issue（供被分配 agent 认领/开工）
        issue_number = None
        if repo:
            body = (
                f"## 任务 {a.get('title', a['task_key'])}\n\n"
                f"- **任务 gid**: `{task['task_id']}`\n"
                f"- **负责角色**: `{a['role']}`\n"
                f"- **功能域**: `{a['domain']}`\n"
                f"- **依赖**: {a.get('depends_on', '无') or '无'}\n"
                f"- **优先级**: {a.get('priority', 'P1')}\n"
                f"- **深度层级**: L2·已分发\n\n"
                f"### 任务描述\n\n{a.get('detail', '')}\n\n"
                f"### 分配来源\n\n"
                f"本 Issue 由「架构·经理」通过分配引擎（L2·分发）创建，"
                f"已注册全局唯一 gid（任务 `{task['task_id']}` / agent `{agent['agent_id']}`）。\n"
            )
            issue_number = _create_issue(repo, a.get("title", a["task_key"]), body)

        results.append({
            "level": 2,
            "task_key": a["task_key"],
            "task_id": task["task_id"],
            "agent_id": agent["agent_id"],
            "role": a["role"],
            "domain": a["domain"],
            "pool_id": pool["pool_id"],
            "issue_number": issue_number,
            "title": a.get("title", ""),
            "depends_on": a.get("depends_on", ""),
            "priority": a.get("priority", "P1"),
            "is_new_task": task["is_new"],
            "is_new_agent": agent["is_new"],
            "status": "dispatched",
        })
    return results


# ============================================================
# L3 触发：投递接力卡 + 等待接单回执
# ============================================================
def dispatch_trigger(assignments, from_agent="架构·经理"):
    """
    L3 · 触发接单层。
    对每个已分发任务：通过消息管线投递接力卡 `[触发:角色]`，
    让被分配 agent 知道有任务、有对应 Issue，可以接单开工。

    输入：L2 产出的分发记录清单
    输出：每条触发消息的投递结果
    """
    results = []
    for a in assignments:
        task_id = a.get("task_id") or a.get("gid")
        agent_id = a.get("agent_id")
        role = a.get("role", "架构·开发")
        issue_number = a.get("issue_number", "")

        # 构建接力卡消息（含 [触发] 标记 + 接单要求）
        relay_card = {
            "trigger": f"[触发:{role}]",
            "depth_level": "L3·触发接单",
            "task_key": a.get("task_key", ""),
            "task_id": task_id,
            "agent_id": agent_id,
            "title": a.get("title", ""),
            "issue": f"#{issue_number}" if issue_number else "(Issue创建失败，请在原始 Issue 中查看分配)",
            "action": "确认接单并开始工作",
            "next_step": "① 回复 [接单] 确认接手 → ② 到对应 Issue 登记开工 → ③ 持续工作并写进度尺 → ④ 交付留痕",
            "expect": "[接单] 回执，无回执不算 L3 完成",
        }
        # 投递消息（定向给被分配 agent）
        msg = admin.post_message(
            topic=f"dispatch.{role}",
            payload=relay_card,
            from_agent=from_agent,
            to_agent=agent_id or "",
        )

        results.append({
            "level": 3,
            "task_key": a.get("task_key", ""),
            "task_id": task_id,
            "agent_id": agent_id,
            "role": role,
            "msg_id": msg.get("msg_id", ""),
            "issue": f"#{issue_number}" if issue_number else "",
            "status": "triggered",
            "expect_receipt": "[接单] 回执待确认",
        })
    return results


# ============================================================
# L3.5 接单确认：agent 收到触发后回执 [接单]
# ============================================================
def accept_assignment(task_key, agent_id, role="架构·开发", note=""):
    """
    L3 接单回执：被分配 agent 回复 [接单] 确认接手任务。

    输入：task_key + agent_id + 接单说明
    输出：接单确认记录
    """
    # 定位任务
    from gid import gid_for
    task_id = gid_for("task", task_key) or task_key
    # 记录接单事件
    admin.record_event(
        agent_id, "accepted",
        {"task_key": task_key, "task_id": task_id,
         "role": role, "note": note or "已接单确认接手"},
        task_id or "",
    )
    # 更新任务状态
    admin.update_task(task_id, "in_progress")
    # 投递确认消息（让经理知道已接单）
    admin.post_message(
        topic="dispatch.accepted",
        payload={"task_key": task_key, "task_id": task_id,
                 "agent_id": agent_id, "role": role,
                 "action": "已确认接单，开始工作",
                 "acceptance": note or "[接单] 任务已接手，目标明确，开始执行"},
        from_agent=agent_id,
        to_agent="架构·经理",
    )
    return {
        "status": "accepted",
        "task_key": task_key,
        "task_id": task_id,
        "agent_id": agent_id,
        "role": role,
        "note": note or "[接单] 任务已接手",
    }


# ============================================================
# L4 工作：开工 → 进度尺推进 → 交付
# ============================================================
def dispatch_start(assignments, from_agent="架构·经理"):
    """
    L4 · 工作执行层 · 开工。
    确认被分配 agent 已接单并开始执行，标记任务状态并留痕。

    输入：L2/L3 产出的分发记录清单
    action：可选，{ "type": "script"/"handler"/"dispatch", ... } 路由执行具体工作动作
    输出：每个任务的开工确认
    """
    results = []
    for a in assignments:
        task_id = a.get("task_id") or a.get("gid")
        agent_id = a.get("agent_id")
        role = a.get("role", "架构·开发")
        action = a.get("action") or {}

        # 更新任务状态为 in_progress（开始工作）
        if task_id:
            admin.update_task(task_id, "in_progress")

        # 留痕：agent 开始工作的事件
        if agent_id:
            admin.record_event(
                agent_id, "work_started",
                {"task_id": task_id, "role": role,
                 "level": "L4·开工", "msg": "已接单并开始执行任务"},
                task_id or "",
            )

        # 差异化补强：L4 支持 action 路由执行（script/handler/dispatch）——"接单后真的在干活"
        action_result = None
        if action:
            action_result = _run_action(action, task_id, role, agent_id, task_key=a.get("task_key", ""))

        results.append({
            "level": 4,
            "task_key": a.get("task_key", ""),
            "task_id": task_id,
            "agent_id": agent_id,
            "role": role,
            "status": "working",
            "action": action.get("type") if action else None,
            "action_result": action_result,
        })
    return results


def _run_action(action, task_id, role, agent_id, task_key=""):
    """执行 L4 工作动作（script/handler/dispatch）。不静默失败：异常显式记 error。"""
    action_type = action.get("type", "work")
    try:
        if action_type == "script":
            import subprocess
            path = action.get("path", "")
            res = subprocess.run(["bash", path], capture_output=True,
                                 text=True, timeout=60)
            if res.returncode == 0:
                return {"type": action_type, "status": "ok",
                        "note": f"脚本执行成功：{path} | {res.stdout.strip()[:200]}"}
            return {"type": action_type, "status": "error",
                    "note": f"脚本执行失败({res.returncode})：{path} | {res.stderr.strip()[:200]}"}
        if action_type == "dispatch":
            from dispatcher import router
            r = router.dispatch({
                "entity": task_key or task_id, "gid": task_id,
                "target_role": action.get("to_role", "架构·测试"),
                "action": "dispatch", "gate": "auto",
            })
            return {"type": action_type, "status": "ok",
                    "note": f"派发到 {r.get('target_agent')}"}
        # handler / 默认 work
        return {"type": action_type, "status": "ok", "note": f"已开工（{action_type}）"}
    except Exception as e:
        return {"type": action_type, "status": "error",
                "note": f"L4 工作执行失败：{type(e).__name__}: {e}"}


def track_progress(task_key, agent_id, target, goal_total, current,
                   note="", role="架构·开发"):
    """
    L4 · 工作执行层 · 进度尺推进。
    每次推进写 goal_meters 刻度，供哨兵收敛判定。

    输入：
      task_key: 任务 key（或 task gid）
      agent_id: 推进该任务的 agent gid
      target: 目标描述
      goal_total: 目标总量
      current: 当前已达量
    输出：刻度 + 哨兵收敛检测结果
    """
    from sentinel import engine as sentinel
    from gid import gid_for
    task_id = gid_for("task", task_key) or task_key
    meter_id = f"g-{task_id}"
    result = sentinel.track(
        meter_id, task_id=task_id, agent_id=agent_id,
        target=target, goal_total=goal_total, current=current,
        note=note,
    )
    return {
        "meter": result["meter"],
        "analysis": result["analysis"],
        "distance": result["meter"].get("distance", 0),
        "delta": result["meter"].get("delta", 0),
    }


def deliver(task_key, agent_id, output, issue_ref="", role="架构·开发"):
    """
    L4 · 工作执行层 · 向上交付。
    标记任务完成，记录交付产物并留痕。

    输入：
      task_key: 任务 key
      agent_id: 交付 agent gid
      output: 交付内容/产物描述
    输出：交付确认
    """
    from gid import gid_for
    task_id = gid_for("task", task_key) or task_key
    # 标记任务完成
    admin.update_task(task_id, "done")
    # 留痕：交付归档
    from data import admin as data_admin
    data_admin.archive(
        f"deliver_{task_id}",
        "deliverable",
        f"任务 {task_key} 交付",
        output,
        source=agent_id,
    )
    # 记录交付事件
    admin.record_event(
        agent_id, "delivered",
        {"task_key": task_key, "task_id": task_id,
         "issue_ref": issue_ref, "output": output},
        task_id or "",
    )
    return {
        "status": "delivered",
        "task_key": task_key,
        "task_id": task_id,
        "agent_id": agent_id,
        "issue_ref": issue_ref,
    }


# ============================================================
# 一站式四层次分发（供经理角色直接调用）
# ============================================================

# ============================================================
# 真实唤醒回执校验（防假装分配 · 修复断链）
# ------------------------------------------------------------
# 用户痛点（Issue #100）：秘书/经理/产品"列个表"调 dispatch() 就当完成，
# 实际没人接单、没唤醒 agent。根因是 dispatch() 的 L3→L4 自动无条件放行，
# 从不校验对端是否真实回执 [接单]。这里补上硬校验：
#   - _has_receipt()    ：某任务的对端 agent 是否有真实接单回执（accepted/awake_ack）
#   - dispatch_verify() ：派发方/哨兵在一站式 dispatch() 后核验真实唤醒状态，
#                         无回执的任务会显式暴露 awaiting_receipt，绝不假装到 L4。
#   - _cloud_receipt()  ：云端语境读取侧——读 Issue/PR **评论流**判 [接单] 回执，
#                         必须走 comment_stream 统一入口（默认全量 + 分页），
#                         否则接口默认 page_size=10 会静默截断、把「已回执」误判成
#                         「链悬空」（Issue #166 · PR #161 真实踩坑）。
# ============================================================
def _has_receipt(task_id, agent_id):
    """检测某任务的对端 agent 是否有真实接单回执（accepted / awake_ack）。

    这是「真实唤醒」的核心判据：只在本地消息管线投了 [触发] 不算唤醒，
    必须对端回执 [接单]/awake_ack（progress 事件）才算真唤醒。
    返回 True=已回执真唤醒 / False=仅投递未唤醒。
    """
    if not task_id or not agent_id:
        return False
    # 直接走 progress 表条件查询（命中 idx_progress_task 索引），
    # 避免拉取全表 5000 条记录后 Python 线性扫描（性能优化）
    from data import db
    row = db.query_one(
        "SELECT 1 FROM progress WHERE task_id=? AND agent_id=? "
        "AND event IN ('accepted', 'awake_ack') LIMIT 1",
        (task_id, agent_id),
    )
    return row is not None


def _cloud_receipt(assignments, since=None, role_keys=None):
    """云端语境：从 Issue/PR **评论流**核验 [接单] 回执（读取侧补充 · Issue #166）。

    与 `_has_receipt()`（本地 progress 事件）双轨互补：云端真实唤醒以平台可见的
    `[接单]` 回执为准。**必须经 `comment_stream.read_comments()` 统一入口读全量**——
    裸调评论接口默认 `page_size=10` 会静默截断，只看到前 10 条就断言"未回执/链悬空"，
    从而触发无效派发（PR #161 真实踩坑）。

    Args:
        assignments: 分发记录清单，每条可带 `issue`/`issue_number`、`role`、
                     `kind`（pull/issue）、`repo`
        since: 可选，只认该时间点之后的评论（ISO 串）
        role_keys: 可选，只认提及这些角色名的回执
    Returns:
        dict: verified_all_awake / awaiting_receipt / degraded / detail
              （degraded 非空 = 评论流没读全，判据可能假阴性，须显式暴露）
    """
    from comment_stream import read_comments

    detail, awaiting, degraded = [], [], []
    for a in assignments or []:
        number = a.get("issue_number") or a.get("issue") or ""
        role = a.get("role") or ""
        if not number:
            continue
        try:
            stream = read_comments(
                kind="pull" if a.get("kind") == "pull" else "issue",
                number=int(str(number).lstrip("#")),
                repo=a.get("repo") or os.environ.get("CNB_REPO"))
        except Exception as e:  # noqa: BLE001 - 读取失败显式暴露，绝不静默判"未回执"
            degraded.append({"issue": number, "role": role, "error": str(e)[:200]})
            detail.append({"issue": number, "role": role, "receipt": False,
                           "error": str(e)[:200]})
            continue

        comments = stream["comments"]
        if since is not None:
            comments = [c for c in comments if (c.get("created_at") or "") >= str(since)]
        bodies = [c.get("body") or c.get("content") or "" for c in comments]
        keys = role_keys or ([role] if role else [])
        got = any("[接单]" in b and (not keys or any(k in b for k in keys))
                  for b in bodies)
        row = {"issue": number, "role": role, "receipt": got,
               "count": len(comments), "complete": stream["complete"],
               "pages": stream["pages"], "source": stream["source"]}
        detail.append(row)
        if not got:
            awaiting.append(dict(row))
        if not stream["complete"]:
            degraded.append({"issue": number, "role": role,
                             "reason": "评论流未读全（分页未取尽），回执判据可能假阴性"})
    return {
        "verified_all_awake": len(awaiting) == 0 and not degraded,
        "total": len(detail),
        "awake_count": len(detail) - len(awaiting),
        "awaiting_receipt_count": len(awaiting),
        "awaiting_receipt": awaiting,
        "degraded": degraded,
        "detail": detail,
        "note": ("评论流读全 + 已见 [接单] 回执" if not awaiting and not degraded else
                 "存在未读全的评论流或未见 [接单] 回执——不得据此断言链悬空/未回执，"
                 "先修读取侧（comment_stream 默认全量）再判"),
    }


def dispatch_verify(assignments):
    """核验一组已派发任务的真实唤醒状态（L4 闸门）。

    输入：dispatch()/dispatch_assign() 产出的分发记录清单（含 task_id/agent_id/role）
    输出：
      verified_all_awake : 是否所有任务都已真实接单（True=可放行到 L4）
      awaiting_receipt   : 未获接单回执、待真实唤醒的任务清单（假装分配会在这里现形）
      detail             : 每个任务的真实唤醒核验明细
    """
    awaiting = []
    detail = []
    for a in assignments:
        task_id = a.get("task_id") or a.get("gid") or ""
        agent_id = a.get("agent_id") or ""
        ok = _has_receipt(task_id, agent_id)
        if not ok:
            awaiting.append({
                "task_key": a.get("task_key", ""),
                "task_id": task_id,
                "agent_id": agent_id,
                "role": a.get("role", ""),
                "issue": a.get("issue_number") or a.get("issue", ""),
            })
        detail.append({
            "task_key": a.get("task_key", ""), "task_id": task_id,
            "agent_id": agent_id, "role": a.get("role", ""),
            "issue": a.get("issue_number") or a.get("issue", ""),
            "receipt": ok,
        })
    return {
        "verified_all_awake": len(awaiting) == 0,
        "total": len(assignments),
        "awake_count": len(assignments) - len(awaiting),
        "awaiting_receipt_count": len(awaiting),
        "awaiting_receipt": awaiting,
        "detail": detail,
        "note": ("所有任务均已获对端 [接单] 回执，真实唤醒成立，可放行到 L4"
                 if len(awaiting) == 0 else
                 "存在未获 [接单] 回执的任务——仅投了接力卡未真唤醒，"
                 "不得假装到 L4，须重触发或升级，绝不静默放行"),
    }


def dispatch(repo, assignments, enable_issue=True):
    """
    经理四层次分发一站式入口（含真实唤醒校验 · Issue #100）。

    L1 声明 → L2 分发 → L3 触发 → (真实唤醒校验闸门) → L4 开工

    ⚠️ 防假装分配：L3 触发只投 [触发] 接力卡，不等于唤醒。本函数会校验对端是否
       真实回执 [接单]/awake_ack——已回执才放行开工（进 L4_start），未回执的
       任务标 awaiting_receipt（不假装开工），并通过 verification / awaiting_receipt
       显式暴露。派发方必须对未回执任务重触发或升级，绝不把"列了清单"当完成。

    输入：
      repo: 仓库名（如 "dongdongxiaozu/dongjiagoushi"）
      assignments: [{task_key, title, role, domain, depends_on, priority, detail}]

    输出：{ L1_declare, L2_dispatch, L3_trigger, L4_start,
            verification(真实唤醒核验), awaiting_receipt(待真实唤醒任务),
            summary(含 started_ok/awake_count/awaiting_receipt_count/levels_reached) }
    """
    # L1 声明
    l1 = declare_assignments(assignments)
    # L2 分发
    l2 = []
    if enable_issue:
        l2 = dispatch_assign(repo, assignments)
    else:
        # 不开平台 Issue 时，仅做本地登记
        for a in assignments:
            _validate_assignment(a)
            task = ops.register_task(a["task_key"], title=a.get("title", ""))
            agent = ops.register_agent_for(a["task_key"], role=a.get("role", "架构·开发"))
            pool = ops.enqueue_task(a["domain"], task["task_id"],
                                    title=a.get("title", ""))
            l2.append({
                "level": 2,
                "task_key": a["task_key"],
                "task_id": task["task_id"],
                "agent_id": agent["agent_id"],
                "role": a["role"],
                "domain": a["domain"],
                "pool_id": pool["pool_id"],
                "issue_number": None,
                "title": a.get("title", ""),
                "depends_on": a.get("depends_on", ""),
                "priority": a.get("priority", "P1"),
                "status": "dispatched",
            })
    # L3 触发接单
    l3 = dispatch_trigger(l2)
    # ---- 真实唤醒回执校验（防假装分配 · Issue #100）----
    # 只在本地消息管线投了 [触发] 接力卡≠真唤醒。必须对端回执 [接单] 才算 L3 完成，
    # 才能放行到 L4。未回执的任务标 awaiting_receipt，不假装开工。
    # verify.detail 已按 task_id/agent_id 逐条判过真实回执，直接复用，避免二次查询
    verify = dispatch_verify(l2)
    l4 = []
    l4_awaiting = []
    for a, vd in zip(l2, verify["detail"]):
        a = dict(a)
        if vd["receipt"]:
            l4.append(a)          # 已有回执 → 放行开工
        else:
            a["status"] = "awaiting_receipt"
            a["depth"] = "L3·待真实唤醒"
            l4_awaiting.append(a) # 未回执 → 阻塞，禁止假装开工

    # 仅对"已获真实回执"的任务开工（未回执的不开工）
    started = dispatch_start(l4) if l4 else []

    return {
        "L1_declare": l1,
        "L2_dispatch": l2,
        "L3_trigger": l3,
        "L4_start": started,
        "verification": verify,          # 真实唤醒核验结果（含 awaiting_receipt 明细）
        "awaiting_receipt": l4_awaiting, # 未获接单回执、待真实唤醒的任务
        "summary": {
            "total_tasks": len(assignments),
            "declared_ok": len(l1),
            "dispatched_ok": len(l2),
            "triggered_ok": len(l3),
            "issues_created": sum(1 for x in l2 if x.get("issue_number")),
            # ⚠️ 真实唤醒统计：只有对端回执 [接单] 并开工的才计入 started/awake
            "started_ok": len(started),
            "awake_count": verify["awake_count"],
            "awaiting_receipt_count": verify["awaiting_receipt_count"],
            "awaiting_receipt_tasks": [x.get("task_key") for x in l4_awaiting],
            # ---- 确认到达层级（max/min 两层 · 防歧义）----
            # 混合场景（部分任务开工到 L4、部分未回执停在 L2）单值 levels_reached
            # 报 4 会让调用方误以为全部到 L4——拆分两层：
            #   levels_reached_max = 任务群中**任一任务**到达的最深层级
            #   levels_reached_min = 任务群中**全部任务**都已到达的层级（保守值）
            #   levels_reached     = min（向后兼容 · 取保守值不谎报）
            # 每个任务的确认深度：receipt=True→dispatch_start 开工到 L4；
            #                      receipt=False→dispatch_trigger 已投接力卡但
            #                      未获 [接单] 回执确认 L3 完成，保守计为 L2。
            "levels_reached_max": (4 if started
                                   else 3 if l3 and verify["awake_count"] > 0
                                   else 2 if l2 else
                                   1 if l1 else 0),
            "levels_reached_min": (4 if len(started) == len(l2) and len(l2) > 0
                                   else 2 if l2 else
                                   1 if l1 else 0),
            "levels_reached": (4 if len(started) == len(l2) and len(l2) > 0
                               else 2 if l2 else
                               1 if l1 else 0),
            "note": ("已获真实 [接单] 回执并放行开工的任务数={started}；"
                     "另有 {aw} 个任务仅投了接力卡未获回执（awaiting_receipt），"
                     "未真实唤醒不得假装到 L4，须由对端回执 [接单] 或派发方重触发/升级。"
                     .format(started=len(started), aw=verify["awaiting_receipt_count"])),
        },
    }


# ============================================================
# 查看分发状态（二级信息）
# ============================================================
def dispatch_overview():
    """查看当前所有已分发任务的全貌（二级信息）。"""
    overview = admin.task_overview()
    return {
        "tasks": overview,
        "pools": admin.list_pools(),
    }


# ============================================================
# 差异化补强：深度俯瞰 + 防跳层校验（辅助架构总师设计落地）
# ============================================================
def _require_level(task_key, needed_level, current_depth):
    """防跳层前置校验：某层执行前须已满足前置深度，否则显式报错。

    needed_level: 该操作需要的最低已达深度（L2 分发=2 / L3 触发=2 / L4 开工=3）
    current_depth: 当前任务已达深度
    """
    if current_depth < needed_level:
        raise ValueError(
            f"防跳层：任务 {task_key} 当前分发深度 {current_depth}，"
            f"须先完成到 L{needed_level}（声明→分发→接单）才可执行该操作。"
        )


def dispatch_depth_overview():
    """按分发深度分组俯瞰各任务（二级信息 · 人类俯瞰）。

    能区分「只声明/只分发」与「已接单继续工作」——回答"哪些任务真正走到了 L4"。
    """
    # 用 repository 直接查询任务 + progress 事件联合判断各层是否发生
    from data import repository as repo
    tasks = repo.list_tasks()
    progress = repo.recent_progress(limit=1000)
    depth_count = {"L1_声明": 0, "L2_分发": 0, "L3_触发接单": 0, "L4_工作交付": 0}
    detail = []
    for t in tasks:
        task_id = t.get("task_id", "")
        status = t.get("status", "")
        events = [p for p in progress if p.get("task_id") == task_id]
        has_accepted = any(p.get("event") == "accepted" for p in events)
        has_delivered = any(p.get("event") == "delivered" for p in events)
        has_work = any(p.get("event") == "work_started" for p in events)
        if has_delivered:
            depth, layer = 4, "L4_工作交付"
        elif has_work or status == "in_progress":
            depth, layer = 3, "L3_触发接单"
        elif status in ("todo", "dispatched"):
            depth, layer = 2, "L2_分发"
        else:
            depth, layer = 1, "L1_声明"
        depth_count[layer] = depth_count.get(layer, 0) + 1
        detail.append({"task_key": t.get("title") or task_id, "task_id": task_id,
                       "depth": depth, "layer": layer, "status": status,
                       "accepted": has_accepted, "delivered": has_delivered})
    return {
        "total_tasks": len(tasks),
        "by_depth": depth_count,
        "reached_L4": depth_count.get("L4_工作交付", 0),
        "note": "L4_工作交付才算派活完成；仅 L1 声明/L2 分发为「名义派活」，须追到接单+工作",
        "detail": detail,
    }


# ============================================================
# 上级「对结果负责」核验：交接责任链是否闭环（Issue #100）
# ------------------------------------------------------------
# dispatch_verify() 面向"一组派发"在派发时刻核验真实唤醒；
# handoff_status() 面向"上级角色"做纵向俯瞰——一次看清该角色
# 派发的所有子任务里 accepted(下级已接单) 与 broken(链条断裂待唤醒)。
# 两者互补：verify 管派发动作，handoff 管"每个上下级对结果负责"。
# ============================================================
def handoff_status(task_ids=None, from_role=""):
    """上级「对结果负责」核验：检查所有派发子任务的交接责任链是否闭环。

    这是用户核心诉求「每个上下级都要对结果负责，不对结果负责链条就是断的」
    的程序化落点——上级角色派发后调本方法，即知哪些下级已真实接单、
    哪些还在『断链待唤醒』，不再凭「列了清单」就当完成。

    返回：
      total       派发任务总数
      accepted    已有 [接单]/awake_ack 真实回执的任务数（下级已对结果负责）
      broken      无回执、链条断裂的任务数（须重触发/升级，不能放行）
      broken_tasks 断链明细
    """
    from data import repository as repo
    progress = repo.recent_progress(limit=10000)
    tasks = repo.list_tasks()
    if task_ids:
        id_set = set(task_ids)
    else:
        id_set = {t.get("task_id") for t in tasks if t.get("task_id")}
    accepted, broken = [], []
    for tid in sorted(id_set):
        evs = [p for p in progress if p.get("task_id") == tid]
        has_accept = any(p.get("event") in ("accepted", "awake_ack") for p in evs)
        has_deliver = any(p.get("event") == "delivered" for p in evs)
        if has_deliver:
            status = "L4·已交付"
        elif has_accept:
            status = "L3·已接单(working)"
        else:
            status = "L2/L3·断链待接单"
        item = {"task_id": tid, "status": status,
                "accepted": has_accept, "delivered": has_deliver}
        if has_accept or has_deliver:
            accepted.append(item)
        else:
            broken.append(item)
    return {
        "total": len(accepted) + len(broken),
        "accepted": len(accepted),
        "broken": len(broken),
        "from_role": from_role,
        "broken_tasks": broken,
        "note": ("对结果负责 = 每个派发子任务都必须有下级真实接单回执并交付；"
                 "broken>0 即链条断裂，须重触发/升级，不得静默放行。"),
    }


if __name__ == "__main__":
    import json
    import argparse

    parser = argparse.ArgumentParser(description="经理分配引擎")
    parser.add_argument("--repo", default="", help="仓库名（如 dongdongxiaozu/dongjiagoushi）")
    parser.add_argument("--assignments", required=True,
                        help='任务分配清单 JSON，如 \'[{"task_key":"T1","title":"任务1","role":"架构·开发","domain":"测试"}]\'')
    parser.add_argument("--no-issue", action="store_true", help="不创建平台 Issue（仅本地登记）")
    args = parser.parse_args()

    assignments = json.loads(args.assignments)
    result = dispatch(args.repo, assignments, enable_issue=not args.no_issue)
    print(json.dumps(result, ensure_ascii=False, indent=2))
