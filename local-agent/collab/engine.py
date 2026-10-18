# -*- coding: utf-8 -*-
"""
collab · 协作运作引擎（engine）
===============================
这是「协作运作机制」的可执行核心：把数据层升级为**有门禁、有层级、有版本、
有整合**的运作引擎。对应 docs/COLLAB_ENGINE.md 五支柱：

  ① 实体解耦 + loc:// 位置寻址   register_entity / resolve / handover
  ② 层级空间                     create_space / space_tree
  ③ 权限空间                     grant / check_access / revoke
  ④ 版本整合                     checkout / update_entity / versions_of
  ⑤ 小组提交                     commit / merge_commit / conflicts

由「架构·数据管理员」统一执行；所有写操作强制 ACL 校验；所有变更留痕。
"""
import json
import uuid

from data import admin, db
from collab import store


# ---------- ① 实体解耦 + loc:// 位置寻址 ----------

def make_loc(etype, namespace, entity_id):
    """构造 loc:// 规范地址。"""
    return f"loc://{etype}.{namespace}/{entity_id}"


def register_entity(etype, namespace, entity_id, payload=None, parent_loc="",
                    acl_key="", owner="data_admin", principal="data_admin"):
    """登记一个实体到注册表（校验写入权限）。"""
    loc = make_loc(etype, namespace, entity_id)
    # 已有实体则要求写权限；新建默认公开+创建者持有
    exist = store.get_entity(loc)
    if exist and not check_access(principal, loc, "w"):
        raise PermissionError(f"[collab] 无权写 {loc}")
    store.upsert_entity(etype, namespace, entity_id, loc, payload, parent_loc,
                        acl_key, owner, version=1)
    admin.record_event(principal, "entity_registered", {"loc": loc, "etype": etype})
    return loc


def resolve(loc, principal="data_admin"):
    """按 loc 解析实体（校验读权限）。"""
    if not check_access(principal, loc, "r"):
        raise PermissionError(f"[collab] 无权读 {loc}")
    ent = store.get_entity(loc)
    if ent is None:
        raise KeyError(f"[collab] 不存在 {loc}")
    return ent


def handover(loc, new_owner, principal="data_admin"):
    """灵活移交：把实体的当前持有权交给另一 agent（校验原持有者/管理权限）。"""
    ent = store.get_entity(loc)
    if ent is None:
        raise KeyError(f"[collab] 不存在 {loc}")
    if not (principal == "data_admin" or principal == ent["owner"]
            or check_access(principal, loc, "w")):
        raise PermissionError(f"[collab] {principal} 无权移交 {loc}")
    old = ent["owner"]
    store.set_entity_owner(loc, new_owner)
    admin.record_event(principal, "entity_handover",
                       {"loc": loc, "from": old, "to": new_owner})
    return {"loc": loc, "from": old, "to": new_owner}


def list_entities(etype=None, namespace=None):
    return store.list_entities(etype, namespace)


# ---------- ② 层级空间（父子树 / 共享空间） ----------

def create_space(space_id, parent_id="", name="", kind="group", owner="data_admin",
                 principal="data_admin"):
    """登记一个空间（父空间存在性校验）。"""
    if parent_id and store.get_space(parent_id) is None:
        raise KeyError(f"[collab] 父空间不存在 {parent_id}")
    store.upsert_space(space_id, parent_id, name, kind, owner)
    admin.record_event(principal, "space_created", {"space_id": space_id, "parent": parent_id})
    return f"loc://space.{space_id}"


def space_tree(root=None):
    """返回父子空间树（俯视图）。"""
    all_spaces = store.list_spaces()

    def build(pid):
        node = {"space_id": pid, "children": []}
        if root is not None and pid == root:
            pass
        for s in all_spaces:
            if s["parent_id"] == pid:
                node["children"].append(build(s["space_id"]))
        return node

    if root is not None:
        base = store.get_space(root)
        return {"space_id": root, "name": base["name"] if base else root,
                "children": build(root)["children"]}
    # 根空间（parent_id==''）可能多个
    return [build(s["space_id"]) for s in all_spaces if s["parent_id"] == ""]


# ---------- ③ 权限空间（ACL） ----------

def _match(pattern, loc):
    """通配符位置匹配：* 匹配任意段。"""
    if pattern == "*":
        return True
    if pattern == loc:
        return True
    # 支持 loc://task.g1/* 形式
    if pattern.endswith("/*"):
        prefix = pattern[:-2]
        return loc.startswith(prefix + "/") or loc == prefix
    return False


def check_access(principal, loc, access="r"):
    """访问校验（强制）：返回 True/False。

    规则：
      - 实体 owner 对其拥有的实体拥有隐式 rw；
      - 否则按 ACL 规则（最具体优先），无规则/为 none 即拒绝。
    """
    # 实体持有者对其实体隐式可读写
    ent = store.get_entity(loc)
    if ent and ent["owner"] == principal:
        return True
    # 数据管理员是数据底座唯一负责人，默认全权
    if principal == "data_admin":
        return True
    rules = store.rules_for(principal)
    # 最具体的匹配（loc_pattern 长度优先）决定结果
    matched = None
    for r in rules:
        if _match(r["loc_pattern"], loc):
            if matched is None or len(r["loc_pattern"]) > len(matched["loc_pattern"]):
                matched = r
    if matched is None:
        return False  # 无规则 = 拒绝
    acc = matched["access"]
    if acc == "none":
        return False
    if access == "r":
        return acc in ("r", "rw")
    if access == "w":
        return acc == "rw"
    return False


def grant(principal, ptype, loc_pattern, access="r", by="data_admin"):
    """授予访问规则（写入留痕）。"""
    store.grant(principal, ptype, loc_pattern, access, by)
    return loc_pattern


def revoke(principal, loc_pattern, by="data_admin"):
    store.revoke(principal, loc_pattern)
    admin.record_event(by, "acl_revoked", {"principal": principal, "loc": loc_pattern})
    return True


def acl_rules():
    return store.acl_rules()


# ---------- ④ 版本整合 ----------

def checkout(loc, principal="data_admin", branch="main"):
    """修改前 checkout：返回当前版本快照 + 基线 vno（读需权限）。"""
    if not check_access(principal, loc, "r"):
        raise PermissionError(f"[collab] {principal} 无权读 {loc}")
    ent = store.get_entity(loc)
    if ent is None:
        raise KeyError(f"[collab] 不存在 {loc}")
    latest = store.latest_version(loc, branch)
    vno = latest if latest > 0 else ent["version"]
    return {"loc": loc, "baseline": vno, "payload": ent["payload"]}


def update_entity(loc, payload, principal="data_admin", branch="main"):
    """写新版本（冲突检测）：基于过期版本提交判定 conflict。"""
    if not check_access(principal, loc, "w"):
        raise PermissionError(f"[collab] {principal} 无权写 {loc}")
    ent = store.get_entity(loc)
    if ent is None:
        raise KeyError(f"[collab] 不存在 {loc}")
    with db.transaction():
        latest = store.latest_version(loc, branch)
        base = latest if latest > 0 else ent["version"]
        new_vno = base + 1
        # 写入新版本
        store.add_version(loc, new_vno, payload, author=principal, branch=branch,
                          parent_vno=base, status="open")
        # 同步主实体指针
        store.update_entity_payload(loc, payload, new_vno)
        admin.record_event(principal, "entity_updated",
                           {"loc": loc, "vno": new_vno, "branch": branch})
        return {"loc": loc, "vno": new_vno, "base": base}


def update_entity_with_base(loc, payload, base_vno, principal="data_admin",
                            branch="main"):
    """带基线版本号的写入（多 agent 并发修改的冲突检测核心）。"""
    if not check_access(principal, loc, "w"):
        raise PermissionError(f"[collab] {principal} 无权写 {loc}")
    ent = store.get_entity(loc)
    if ent is None:
        raise KeyError(f"[collab] 不存在 {loc}")
    # 读 latest → 写新版本 必须在同一事务内（消除 TOCTOU 竞态）
    with db.transaction():
        latest = store.latest_version(loc, branch)
        if latest > base_vno:
            # 主干已前进：基于过期版本 → 冲突（独立编号，不推进主线）
            cv = store.add_conflict_version(loc, payload, author=principal,
                                            branch=branch, parent_vno=base_vno)
            admin.record_event(principal, "version_conflict",
                               {"loc": loc, "base": base_vno, "latest": latest})
            return {"loc": loc, "vno": cv["vno"], "base": base_vno, "latest": latest,
                    "status": "conflict"}
        new_vno = latest + 1
        store.add_version(loc, new_vno, payload, author=principal, branch=branch,
                          parent_vno=base_vno, status="open")
        store.update_entity_payload(loc, payload, new_vno)
        admin.record_event(principal, "entity_updated",
                           {"loc": loc, "vno": new_vno, "base": base_vno})
        return {"loc": loc, "vno": new_vno, "base": base_vno, "status": "ok"}


def versions_of(loc):
    return store.versions_of(loc)


# ---------- ⑤ 小组提交 ----------

def commit(group_loc, scope, entity_locs, base_versions, submitter="data_admin"):
    """小组提交：声明最小模块粒度 + 各实体父版本，供整合。"""
    commit_id = f"commit-{uuid.uuid4().hex[:12]}"
    store.add_commit(commit_id, group_loc, scope, entity_locs, base_versions,
                     submitter, status="open")
    admin.record_event(submitter, "commit_submitted",
                       {"commit_id": commit_id, "scope": scope, "group": group_loc})
    return commit_id


def merge_commit(commit_id):
    """合并提交进主线：逐个实体做冲突检测，全通过才 merged。"""
    c = store.get_commit(commit_id)
    if c is None:
        raise KeyError(f"[collab] 不存在提交 {commit_id}")
    if c["status"] != "open":
        return {"commit_id": commit_id, "status": c["status"], "changed": False}
    merged = True
    details = []
    for loc, base in zip(c["entity_locs"], c["base_versions"]):
        ent = store.get_entity(loc)
        if ent is None:
            merged = False
            details.append({"loc": loc, "status": "missing"})
            continue
        latest = store.latest_version(loc, "main")
        if latest > int(base or 0):
            # 主线已前进：需要 rebase，标记冲突
            merged = False
            details.append({"loc": loc, "status": "conflict",
                            "base": base, "latest": latest})
    status = "merged" if merged else "conflict"
    store.set_commit_status(commit_id, status)
    admin.record_event("data_admin", "commit_" + status,
                       {"commit_id": commit_id, "scope": c["scope"]})
    return {"commit_id": commit_id, "status": status, "details": details}


def commits(status=None, group_loc=None):
    return store.commits(status, group_loc)


def conflicts():
    """待处理冲突清单（含冲突版本与冲突提交）。

    直接按 status 直查，不走 versions_of 的「按 vno DESC 限 50」窗口：
    冲突提案用负数编号，在 DESC 里排最后，一旦主线版本 ≥50 就会被窗口截掉，
    导致冲突静默丢失（DD-4 受理闸门拿不到提案）。
    """
    conf_versions = store.conflict_versions()
    conf_commits = store.commits(status="conflict")
    return {"version_conflicts": conf_versions, "commit_conflicts": conf_commits}


# ---------- 需求 / skill / 记忆（一等实体，解耦共享） ----------

def add_requirement(req_id, title="", space="", detail=None, status="open",
                    parent_req="", owner="data_admin"):
    store.upsert_req(req_id, title, space, detail, status, parent_req, owner)
    admin.record_event(owner, "req_registered", {"req_id": req_id, "space": space})
    return req_id


def register_skill(skill_id, name="", space="", desc="", playbook="", owner="data_admin"):
    store.upsert_skill(skill_id, name, space, desc, playbook, owner)
    admin.record_event(owner, "skill_registered", {"skill_id": skill_id, "space": space})
    return skill_id


def write_memory(mem_id, space, kind, content, owner, principal="data_admin"):
    """写记忆（受 ACL 管控：写入需空间写权限）。"""
    loc = make_loc("mem", space, mem_id)
    if not check_access(principal, loc, "w"):
        raise PermissionError(f"[collab] {principal} 无权写记忆 {loc}")
    store.upsert_memory(mem_id, space, kind, content, owner)
    admin.record_event(principal, "memory_written", {"mem_id": mem_id, "space": space})
    return loc


def read_memory(mem_id, space, principal="data_admin"):
    """读记忆（受 ACL 管控：读取需空间读权限）。"""
    loc = make_loc("mem", space, mem_id)
    if not check_access(principal, loc, "r"):
        raise PermissionError(f"[collab] {principal} 无权读记忆 {loc}")
    m = store.get_memory(mem_id)
    if m is None:
        raise KeyError(f"[collab] 不存在记忆 {mem_id}")
    return m


def list_memory(space=None, kind=None):
    return store.list_memory(space, kind)
