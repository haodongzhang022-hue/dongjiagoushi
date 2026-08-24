# -*- coding: utf-8 -*-
"""
数据管理层 · 数据管理员职责（admin）
====================================
本模块是「架构·数据管理员」角色的**可执行核心**：把"数据管理"这一职责
**写成规则、由数据管理员 agent 负责**落地执行。涵盖 2500 并发 agent 协作
所需的四大数据底座：

  | 职责块          | 说明                                                  |
  |-----------------|-------------------------------------------------------|
  | 内容存档         | agents 档案登记 + 协作产出归档（archives）             |
  | 进度统计         | 进度事件流水（progress）+ 聚合指标快照（stats）         |
  | 消息管线         | 消息入队/消费/回放/广播（messages）                    |
  | 任务存储         | 任务登记/状态流转/依赖（tasks）                        |

数据管理员职责规则（写入 docs/DATA_ARCHITECTURE.md）：
  1. **数据先行**：每个 agent/任务/消息在进业务前，先由数据管理员登记入库；
  2. **统一口径**：所有指标统计以 stats/progress 为准，禁止各 agent 自造统计；
  3. **可回溯**：任何协作产出必须留痕（archives），禁止无痕产出；
  4. **消息可回放**：消息管线可重放，供审计与复盘，不吞异常；
  5. **数据管理员唯一负责**：数据写入/校验/统计/归档由本角色统一执行，
     人类/总师只通过二级信息（看板/统计）俯瞰，不直接触碰原始库。
"""
from . import db, schema, repository as repo


def init():
    """初始化数据库：建表 + 登记数据管理员档案。"""
    tables = schema.init_schema()
    repo.upsert_agent(
        agent_id="data_admin",
        role="架构·数据管理员",
        group_id="system",
        status="active",
        spec={"backend": db.backend(), "tables": tables},
    )
    return {"backend": db.backend(), "tables": tables}


# ---------- 内容存档 ----------
def register_agent(agent_id, role, group_id="", status="in_progress", spec=None):
    """数据管理员登记一个 agent 档案，并留进度事件。"""
    repo.upsert_agent(agent_id, role, group_id, status, spec)
    repo.record_progress(agent_id, "registered", {"role": role, "status": status})
    return agent_id


def archive(archive_id, kind, title, content, source=""):
    """数据管理员写入一条内容存档，并留进度事件。"""
    repo.add_archive(archive_id, kind, title, content, source)
    repo.record_progress("data_admin", "archived", {"archive_id": archive_id, "kind": kind})
    return archive_id


def archive_agents_snapshot(label="snapshot"):
    """将当前全部 agent 档案归档为一个快照（里程碑级存档）。"""
    agents = repo.list_agents()
    return archive(
        f"agents_snapshot_{label}_{db.now_iso()}",
        "milestone",
        f"agent 档案快照 {label}",
        agents,
        "data_admin",
    )


# ---------- 进度统计 ----------
def record_event(agent_id, event, detail="", task_id=""):
    """记录一条进度事件。"""
    repo.record_progress(agent_id, event, detail, task_id)
    return event


def snapshot_stats():
    """生成并落库一组聚合指标快照（进度统计 · 供看板）。"""
    repo.record_stat("concurrent_agents", repo.count_agents(), "count")
    repo.record_stat("pending_messages", repo.pending_count(), "count")
    repo.record_stat("total_tasks", repo.count_tasks(), "count")
    repo.record_stat("done_tasks", repo.count_tasks(status="done"), "count")
    repo.record_stat("archives", repo.count_archives(), "count")
    return repo.latest_stats()


def progress_report():
    """生成进度统计报告（二级信息，供人类/总师俯瞰）。"""
    agents = repo.count_agents()
    pending = repo.pending_count()
    tasks = repo.count_tasks()
    done = repo.count_tasks(status="done")
    archives = repo.count_archives()
    events = repo.progress_count()
    return {
        "agents": agents,
        "pending_messages": pending,
        "tasks": {"total": tasks, "done": done, "open": tasks - done},
        "archives": archives,
        "progress_events": events,
    }


# ---------- 消息管线 ----------
def post_message(topic, payload, from_agent="system", to_agent=""):
    """数据管理员投递一条消息（消息管线入队）。"""
    return repo.enqueue_message(topic, payload, from_agent, to_agent)


def deliver(agent_id, topic, payload, from_agent="system"):
    """定向投递消息给指定 agent。"""
    return repo.enqueue_message(topic, payload, from_agent, to_agent=agent_id)


def broadcast(topics, payload, from_agent="system"):
    """向一组 topic 广播消息。"""
    return repo.fan_out(topics, payload, from_agent)


def consume(agent_id=None, topic=None):
    """消费一条待处理消息（消息管线 FIFO）。"""
    return repo.consume_next(to_agent=agent_id, topic=topic)


def pending(agent_id=None, topic=None):
    """查询某 agent/某 topic 的待处理消息数。"""
    return repo.pending_count(to_agent=agent_id, topic=topic)


def replay(topic, limit=100):
    """回放某 topic 消息（审计/复盘）。"""
    return repo.replay_topic(topic, limit)


# ---------- 任务存储 ----------
def assign_task(task_id, title="", assignee="", depends_on="", status="todo", detail=""):
    """数据管理员登记一个任务并留进度事件。"""
    repo.upsert_task(task_id, title, assignee, depends_on, status, detail)
    repo.record_progress(assignee or "data_admin", "task_assigned",
                         {"task_id": task_id, "status": status}, task_id)
    return task_id


def update_task(task_id, status):
    """更新任务状态，并留进度事件。"""
    repo.update_task_status(task_id, status)
    repo.record_progress("data_admin", "task_updated",
                         {"task_id": task_id, "status": status}, task_id)
    return status


def task_overview():
    """任务全貌（二级信息）。"""
    return {
        "total": repo.count_tasks(),
        "todo": repo.count_tasks(status="todo"),
        "in_progress": repo.count_tasks(status="in_progress"),
        "done": repo.count_tasks(status="done"),
        "blocked": repo.count_tasks(status="blocked"),
    }
