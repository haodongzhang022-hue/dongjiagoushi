# -*- coding: utf-8 -*-
"""
自适应 @ 定位解析器（resolver · 核心）
======================================
把「@谁、@哪个仓库的谁」从写死的字符串，变成**根据触发仓库自动解析**的机制。

背景（用户纠偏 · Issue #33）：
  此前身份声明 / 跨库召唤写死 `dongdongxiaozu/youkaifaxilieagent(CodeBuddy)`，
  存在两个硬伤：
    1. **角色名/承载仓库写死**：触发本仓库 CodeBuddy 的可能不是
       `youkaifaxilieagent`（用户原文：『这里不能写死 youkaifaxilieagent，
       因为触发的可能不是 youkaifaxilieagent』），org 甚至可能不是
       `dongdongxiaozu`。
    2. **跨库权限受限**：到其他仓库协作时，若仍用本仓库的 @ 去召唤，会因
       「角色不属于该仓库」而权限受限（每个角色的权限通常只覆盖其所属仓库）。

本模块把「召唤目标」抽象为可自适应的要素，并区分**两个仓库维度**：

  ╔═ 角色承载仓库（agent 自身所属）═══════════════════════════════╗
  ║ CodeBuddy NPC 由某个仓库承载，用 `@org/承载仓库(CodeBuddy)`     ║
  ║ 触发。该承载仓库常与「被操作的业务仓库」不同——例如            ║
  ║ `@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)` 触发一个        ║
  ║ CodeBuddy 去操作 `dongdongxiaozu/dongjiagoushi`。               ║
  ╚═════════════════════════════════════════════════════════════════╝
  ╔═ 操作仓库（agent 正在为其工作的仓库）═══════════════════════════╗
  ║ 由 git remote / 环境变量探测，或显式传入。                       ║
  ╚═════════════════════════════════════════════════════════════════╝

能力（每个 agent 通过 BaseRole 挂载 HandleAbility 获得）：
  - 从会话注入的 `@org/repo(role)` 触发串中**识别出自身角色承载仓库**；
  - 探测当前操作仓库（org/repo）；
  - 按**目标仓库**解析出正确的 `@org/repo(角色)` 完整格式；
  - **跨库 / 同库判定**：同仓库允许复用本仓库 @（防冗余），跨仓库必须用目标
    仓库的完整 @（保证权限够用）；
  - **角色权限建议**：给出目标仓库可用角色的召唤建议，避免因选错角色而受限。

关键原则（对齐 AGENTS.md）：
  - **不写死**：任何角色名 / org / repo 都不 hardcode，全部可覆盖、可探测、可回退；
  - **全仓库指向**：本模块是通用能力，每个 agent 都挂载，跨库协作时自动用目标
    仓库的 @，不再依赖写死的当前角色名；
  - **防重复**：同仓库先检测能复用就不重造；跨仓库才走完整解析。
"""
import os
import re

# ---------------------------------------------------------------------------
# 约定与默认值（仅作为解析回退基线，非写死目标）
# ---------------------------------------------------------------------------
# 当前操作仓库的默认 org/repo（可被环境变量 / git remote / 触发格式覆盖）
DEFAULT_ORG = "dongdongxiaozu"
DEFAULT_REPO = "dongjiagoushi"

# CNB 平台 CodeBuddy 兜底角色名（触发时若未指明角色，用此兜底）
DEFAULT_CODEBUDDY_ROLE = "CodeBuddy"

# 支持的 @ 触发格式
_AT_FULL_RE = re.compile(
    r"@\s*(?P<full>[\w.-]+/[\w.-]+)\s*(?:\(\s*(?P<role>[^()]+?)\s*\))?"
)
_AT_SINGLE_RE = re.compile(r"@\s*(?P<name>[\w.-]+)")


def _git_remote_org_repo():
    """从 git remote 探测当前**操作仓库**的 org/repo。

    解析 `https://cnb.cool/org/repo.git` / `git@...:org/repo.git` /
    `org/repo` 形式。失败返回 (None, None)。
    """
    try:
        import subprocess
        out = subprocess.run(
            ["git", "remote", "-v"], capture_output=True, text=True,
            timeout=5, check=False,
        ).stdout
    except Exception:
        return None, None
    first = None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            first = parts[1]
            break
    if not first:
        return None, None
    # 兼容 cnb.cool / gitcode / github / git@ 等多种 host 与 .git 后缀
    m = re.search(r"(?:[/:]|^)([\w.-]+/[\w.-]+?)(?:\.git)?(?:\s|$)", first)
    if not m:
        return None, None
    org_repo = m.group(1)
    if "/" in org_repo:
        org, repo = org_repo.split("/", 1)
        return org, repo
    return None, None


def _env_org_repo():
    """从环境变量探测当前操作仓库的 org/repo。

    识别源（按优先级）：
      1. CNB 平台实际注入变量（最权威，运行时不依赖 git remote）：
         - `CNB_GROUP_SLUG`（org / 组织）+ `CNB_REPO_NAME`（仓库名）
         - `CNB_ROOT_SLUG`（根命名空间，org 兜底）+ `CNB_REPO_NAME`
         - `CNB_ORG` / `CNB_REPO`（通用别名，兼容其他宿主）
      2. GIT 通用变量：`GIT_ORG` / `GIT_REPO`（本地/CI 兜底）。
    这些让仓库识别**不假设 org 固定**（用户诉求：『甚至 dongdongxiaozu 都不一定对』），
    并能在 git remote 缺失或解析失败时仍用平台权威值正确识别当前仓库。
    """
    # CNB 平台实际注入：org = CNB_GROUP_SLUG / CNB_ROOT_SLUG，repo = CNB_REPO_NAME
    org = (os.environ.get("CNB_GROUP_SLUG") or os.environ.get("CNB_ROOT_SLUG")
           or os.environ.get("CNB_ORG"))
    repo = (os.environ.get("CNB_REPO_NAME") or os.environ.get("CNB_REPO"))
    if org and repo:
        return org, repo
    # GIT 通用变量（本地 / 其他 CI 兜底）
    org = os.environ.get("GIT_ORG")
    repo = os.environ.get("GIT_REPO")
    if org and repo:
        return org, repo
    return None, None


def detect_current_org_repo():
    """探测当前**操作仓库**的 org/repo。

    探测顺序：环境变量 → git remote → 默认约定。绝不返回 None（有默认兜底）。
    """
    org, repo = _env_org_repo()
    if org and repo:
        return org, repo
    org, repo = _git_remote_org_repo()
    if org and repo:
        return org, repo
    return DEFAULT_ORG, DEFAULT_REPO


def parse_at(at_str):
    """解析一个 @ 触发串 → { org, repo, role }。

    支持：
      "@org/repo(角色)"  "@org/repo"  "@repo"  "@CodeBuddy"
      "org/repo(角色)"（无 @ 前缀同样解析）
    无法解析返回 None。
    """
    if not at_str:
        return None
    s = at_str.strip()
    m = _AT_FULL_RE.search(s)
    if m:
        full = m.group("full")
        role = m.group("role")
        org, repo = full.split("/", 1)
        return {
            "org": org.strip(),
            "repo": repo.strip(),
            "role": (role or DEFAULT_CODEBUDDY_ROLE).strip(),
        }
    m = _AT_SINGLE_RE.search(s)
    if m:
        name = m.group("name").strip()
        org, repo = detect_current_org_repo()
        if "/" in name:
            o, r = name.split("/", 1)
            return {"org": o.strip(), "repo": r.strip(),
                    "role": DEFAULT_CODEBUDDY_ROLE}
        return {"org": org, "repo": name, "role": DEFAULT_CODEBUDDY_ROLE}
    if "/" in s and "(" in s:
        body, role = s.split("(", 1)
        role = role.rstrip(")")
        if "/" in body:
            org, repo = body.strip().split("/", 1)
            return {"org": org.strip(), "repo": repo.strip(),
                    "role": role.strip() or DEFAULT_CODEBUDDY_ROLE}
    return None


def format_at(org, repo, role=None):
    """按 org/repo/role 生成标准 `@org/repo(角色)` 格式。"""
    role = role or DEFAULT_CODEBUDDY_ROLE
    return f"@{org}/{repo}({role})"


def is_cross_repo(target_org=None, target_repo=None, current_org=None,
                  current_repo=None):
    """判定目标仓库与当前**操作仓库**是否**跨仓库**。

    - 未给出目标仓库 → False（无跨库需求，复用本仓库即可）；
    - 目标 org/repo 与当前 org/repo 均一致 → 同仓库（False）；
    - 任一不一致 → 跨仓库（True）。
    参数缺省时自动探测当前仓库。
    """
    if not target_org and not target_repo:
        return False
    c_org, c_repo = current_org, current_repo
    if not c_org or not c_repo:
        c_org, c_repo = detect_current_org_repo()
    if target_org and target_org != c_org:
        return True
    if target_repo and target_repo != c_repo:
        return True
    return False


def resolve(at_str=None, target_org=None, target_repo=None, role=None,
            current_org=None, current_repo=None):
    """核心：把『当前触发上下文』解析为『正确的召唤目标』。

    入参说明：
      at_str       调用方已给出的 @ 触发串（可能写死/不规范），可选。
                   若命中，用于识别**自身 CodeBuddy 角色承载仓库**；
      target_org   目标仓库 org（跨库协作目标）；
      target_repo  目标仓库 repo；
      role         目标角色名；缺省按目标仓库解析 CodeBuddy 兜底；
      current_org/current_repo  当前操作仓库（缺省自动探测）。

    返回 dict：
      {
        "trigger": {org, repo, role},   # 从触发串识别出的自身角色承载仓库
        "current": {org, repo},         # 当前操作仓库
        "target": {org, repo, role},    # 解析出的目标三要素
        "handle": "@org/repo(角色)",     # 标准召唤格式（最终答案）
        "cross_repo": bool,             # 是否跨仓库
        "source": str,                  # 解析来源
        "permission_note": str,         # 权限建议
      }
    """
    # 1) 触发串识别自身 CodeBuddy 角色承载仓库
    trigger = None
    if at_str:
        trigger = parse_at(at_str)
        if trigger is None:
            trigger = {"org": None, "repo": None,
                       "role": DEFAULT_CODEBUDDY_ROLE}

    # 2) 当前操作仓库
    c_org, c_repo = current_org, current_repo
    if not c_org or not c_repo:
        c_org, c_repo = detect_current_org_repo()

    # 3) 目标三要素（优先级：显式 target > 触发串 trigger > 当前操作仓库）
    #    只有当显式 target 未给全时，才用触发串/当前仓库补全——不混用、不覆盖。
    t_org = target_org
    t_repo = target_repo
    t_role = role
    src = "default"
    explicit = bool(target_org or target_repo or role)
    # 显式 target 未给全的维度，从触发串（自身角色承载仓库）补
    trig_org = trigger.get("org") if trigger else None
    trig_repo = trigger.get("repo") if trigger else None
    trig_role = trigger.get("role") if trigger else None
    if t_org is None:
        t_org = trig_org
    if t_repo is None:
        t_repo = trig_repo
    if not t_role:
        t_role = trig_role or DEFAULT_CODEBUDDY_ROLE
    # 仍未定的维度回退到当前操作仓库
    if t_org is None:
        t_org = c_org
    if t_repo is None:
        t_repo = c_repo
    if not t_role:
        t_role = DEFAULT_CODEBUDDY_ROLE
    # 解析来源标注
    if explicit:
        src = "target"
    elif trigger and trig_org and trig_repo:
        src = "trigger"
    else:
        src = "probe"

    # 4) 跨库判定（相对当前操作仓库）
    cross = is_cross_repo(t_org, t_repo, c_org, c_repo)

    # 5) 标准 handle
    handle = format_at(t_org, t_repo, t_role)

    # 6) 权限建议
    if cross:
        note = (
            f"目标仓库 {t_org}/{t_repo} 与当前操作仓库 {c_org}/{c_repo} 不同，"
            f"属于跨仓库协作，必须用目标仓库完整 @ 召唤 `{handle}`；"
            f"否则该角色无目标仓库权限（角色权限通常只覆盖其所属仓库）。"
        )
    else:
        note = (
            f"目标仓库 {t_org}/{t_repo} 与当前操作仓库一致，可复用本仓库 @ "
            f"`{handle}`（同仓复用，防冗余）；若需更高权限/其他角色，可按 "
            f"`@org/repo(角色)` 显式指定。"
        )

    return {
        "trigger": {
            "org": trigger["org"] if trigger else None,
            "repo": trigger["repo"] if trigger else None,
            "role": trigger["role"] if trigger else None,
        },
        "current": {"org": c_org, "repo": c_repo},
        "target": {"org": t_org, "repo": t_repo, "role": t_role},
        "handle": handle,
        "cross_repo": cross,
        "source": src,
        "permission_note": note,
    }


# 便捷别名
resolve_handle = resolve


__all__ = [
    "DEFAULT_ORG", "DEFAULT_REPO", "DEFAULT_CODEBUDDY_ROLE",
    "detect_current_org_repo", "parse_at", "format_at",
    "is_cross_repo", "resolve", "resolve_handle",
]
