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
from . import db, migrate, schema, repository as repo


def init():
    """初始化数据库：建表 + 迁移既有库 + 登记数据管理员档案。

    迁移是幂等的：新库为空时整体 skip；旧库则补齐 versions 唯一键与冲突编号。
    """
    # init_schema() 内部已跑迁移；此处只取结果用于汇报，不重复执行
    tables = schema.init_schema()
    migration = migrate.last_result()
    repo.upsert_agent(
        agent_id="data_admin",
        role="架构·数据管理员",
        group_id="system",
        status="active",
        spec={"backend": db.backend(), "tables": tables},
    )
    return {"backend": db.backend(), "tables": tables, "migration": migration}


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


# ================= 全局唯一编号（gid · 精准定位/二次触发同一实体） =================

def _ensure_gid_schema():
    """确保 gid_registry 表存在（幂等，供 gid 系列函数前置调用）。"""
    schema.init_schema()


def registry_get(etype, biz_key):
    """查某业务 key 已登记的全局唯一 gid（未登记返回 None）。"""
    _ensure_gid_schema()
    return repo.registry_get(etype, biz_key)


def registry_set(etype, biz_key, gid):
    """登记某业务 key 的全局唯一 gid（幂等）。"""
    _ensure_gid_schema()
    repo.registry_set(etype, biz_key, gid)
    record_event("data_admin", "gid_registered",
                 {"etype": etype, "biz_key": biz_key, "gid": gid})
    return gid


def registry_lookup(gid):
    """按全局唯一 gid 反查其类型/业务 key（精准定位某实体）。"""
    _ensure_gid_schema()
    return repo.registry_lookup_by_gid(gid)


def register_gid(etype, biz_key):
    """为业务 key 登记/取回同一个全局唯一 gid（二次触发拿同一 ID）。

    返回 (gid, is_new)。
    """
    _ensure_gid_schema()
    exist = repo.registry_get(etype, biz_key)
    if exist:
        return exist, False
    from gid import gen
    gid = gen(etype)
    repo.registry_set(etype, biz_key, gid)
    record_event("data_admin", "gid_registered",
                 {"etype": etype, "biz_key": biz_key, "gid": gid})
    return gid, True


# ================= 功能域任务池（pool · 按任务负载动态扩展 agent） =================

def upsert_pool(pool_id, domain, parent_pool="", capacity=0, load=0.0, status="active"):
    repo.upsert_pool(pool_id, domain, parent_pool, capacity, load, status)
    record_event("data_admin", "pool_upserted",
                 {"pool_id": pool_id, "domain": domain, "capacity": capacity})
    return pool_id


def get_pool(pool_id):
    return repo.get_pool(pool_id)


def list_pools(domain=None, status=None):
    return repo.list_pools(domain, status)


def resize_pool(pool_id, capacity):
    """按任务负载动态调整某池并发容量（扩容/缩容）。"""
    repo.update_pool_capacity(pool_id, capacity)
    record_event("data_admin", "pool_resized",
                 {"pool_id": pool_id, "capacity": capacity})
    return capacity


def pool_overview():
    """功能域任务池全貌（二级信息）。"""
    pools = repo.list_pools()
    return {
        "total_pools": len(pools),
        "total_capacity": sum(p["capacity"] for p in pools),
        "total_load": sum(p["load"] for p in pools),
        "pools": pools,
    }


# ================= 任务拆分 / 加派（小组长整合） =================

def add_split(parent_task, branch_task, agent_id, reason="", submitter="", status="open"):
    """登记一次任务拆分/加派（大任务拆分支 / 开发中途申报加派）。"""
    from gid import gen
    split_id = gen("split")
    repo.add_split(split_id, parent_task, branch_task, agent_id, reason, submitter, status)
    record_event(submitter or "data_admin", "task_split",
                 {"split_id": split_id, "parent": parent_task,
                  "branch": branch_task, "agent": agent_id, "reason": reason},
                 parent_task)
    return split_id


def splits_of(parent_task, status="open"):
    return repo.split_of(parent_task, status)


def aggregate_split(split_id):
    """小组长把某拆分分支的产出汇总整合（标记已聚合）。"""
    repo.set_split_status(split_id, "aggregated")
    record_event("架构·小组长", "split_aggregated", {"split_id": split_id})
    return split_id


def split_overview(status="open"):
    """任务拆分/加派全貌（二级信息）。"""
    return repo.list_splits(status)


# ================= 任务 PR/Issue 映射（1-3 PR，各按独立 Issue） =================

def add_task_pr(task_id, agent_id, seq=1, kind="new", issue_id="", status="open"):
    """为一个任务提交登记一个 PR（每个任务可 1-3 个 PR）。"""
    from gid import gen
    pr_id = gen("pr")
    if not issue_id:
        issue_id = gen("issue")
    repo.add_task_pr(pr_id, task_id, agent_id, issue_id, seq, kind, status)
    record_event(agent_id, "pr_submitted",
                 {"pr_id": pr_id, "task_id": task_id, "seq": seq,
                  "issue_id": issue_id, "kind": kind},
                 task_id)
    return pr_id, issue_id


def prs_for_task(task_id, status=None):
    return repo.prs_for_task(task_id, status)


def prs_for_agent(agent_id, status=None):
    return repo.prs_for_agent(agent_id, status)


def pr_count_for_task(task_id, status=None):
    return repo.pr_count_for_task(task_id, status)


def amend_task_pr(task_id, agent_id, seq):
    """对某任务已有 PR 的修改再提交（kind=amend，不新增独立 Issue）。"""
    prs = repo.prs_for_task(task_id)
    target = next((p for p in prs if p["seq"] == seq), None)
    if target is None:
        raise KeyError(f"任务 {task_id} 无第 {seq} 个 PR 可修改")
    repo.add_task_pr(gen_pr(), task_id, agent_id, target["issue_id"], seq, "amend", "open")
    record_event(agent_id, "pr_amended",
                 {"task_id": task_id, "seq": seq, "pr_id": target["pr_id"]}, task_id)
    return target


def gen_pr():
    from gid import gen
    return gen("pr")
