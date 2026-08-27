# -*- coding: utf-8 -*-
"""
接力卡触发校验能力包（relay_card · 全员防断链工具）
==================================================
把「接力卡必须带完整 @ + [触发] 标记」从仓库 rules 沉淀为**可执行校验工具**，
从根上杜绝『交付方用 @CodeBuddy 没带 [触发:角色全称] 导致下游角色没被唤醒、
链条断裂』的协作故障。

设计理念（用户拍板 · 触发强制化工具化）：
  - AGENTS.md「触发强制化·①显式声明触发最高优先」要求接力卡必须带
    `[触发:<角色全称>]` 标记，缺标记即视为无效接力卡，不猜测接手角色；
  - 但该规则此前**只靠自觉、无机器拦截**，开发落地时 @CodeBuddy 断链无人拦；
  - 本工具把规则落成 `check` 校验 + `gen` 生成器，供交付/接力动作前置调用。

能力维度：
  ╔═ check ═══════════════════════════════════════════════════════╗
  ║ check(text)     校验交付/接力文本是否含完整 @org/repo(角色)     ║
  ║                 + [触发:<角色全称>]；缺标记返回 INVALID_RELAY    ║
  ║ check_required( 强制版：缺任意标记即判无效（CI 红灯拦截用）      ║
  ║   text, role)                                                   ║
  ╚════════════════════════════════════════════════════════════════╝
  ╔═ gen ══════════════════════════════════════════════════════════╗
  ║ gen(to_role)    基于当前仓库动态生成合规接力卡 @ 模板            ║
  ║                 （复用 HandleAbility 不写死角色/仓库，动态解析） ║
  ╚════════════════════════════════════════════════════════════════╝

用法（任意角色 / 脚本 / CI 直接调用）：
    from relay_card import check, gen
    ok, reasons = check("@dongdongxiaozu/dongjiagoushi(架构·评审) [触发:架构·评审]")
    print(gen("架构·评审"))      # 生成合规接力卡 @ 模板

CLI：
    python -m relay_card check "<交付文本>"
    python -m relay_card check --role 架构·评审 "<文本>"
    python -m relay_card gen --to 架构·评审
"""
import os
import re
import sys

__all__ = ["check", "check_required", "gen", "ROLES_ALIAS"]

# 确保 local-agent 目录在 sys.path（便于导入 handle.resolver）
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

# 规范角色名（架构·团队命名空间，统一加「架构·」前缀）
ROLES = [
    "架构·秘书", "架构·产品", "架构·总师", "架构·经理",
    "架构·开发", "架构·评审", "架构·测试", "架构·监控哨兵",
    "架构·数据管理员", "架构·小组长", "架构·进度推手",
    "架构·审核前置助手", "架构·总师助理", "架构·工具开发",
]

# 角色别名 → 规范名（防 AI 写别名不匹配）
ROLES_ALIAS = {
    "评审": "架构·评审", "架构评审": "架构·评审", "reviewer": "架构·评审",
    "开发": "架构·开发", "架构开发": "架构·开发", "dev": "架构·开发",
    "测试": "架构·测试", "架构测试": "架构·测试", "qa": "架构·测试",
    "产品": "架构·产品", "架构产品": "架构·产品", "pm": "架构·产品",
    "总师": "架构·总师", "架构总师": "架构·总师", "architect": "架构·总师",
    "经理": "架构·经理", "架构经理": "架构·经理", "manager": "架构·经理",
    "秘书": "架构·秘书", "架构秘书": "架构·秘书", "secretary": "架构·秘书",
    "哨兵": "架构·监控哨兵", "监控哨兵": "架构·监控哨兵", "sentinel": "架构·监控哨兵",
    "小组长": "架构·小组长", "架构小组长": "架构·小组长", "lead": "架构·小组长",
    "数据管理员": "架构·数据管理员", "架构数据管理员": "架构·数据管理员",
    "进度推手": "架构·进度推手", "架构进度推手": "架构·进度推手",
    "审核前置助手": "架构·审核前置助手", "架构审核前置助手": "架构·审核前置助手",
    "总师助理": "架构·总师助理", "架构总师助理": "架构·总师助理",
    "工具开发": "架构·工具开发", "架构工具开发": "架构·工具开发",
}


def _normalize_role(role):
    """把别名/缺前缀角色归一化为规范角色全称。"""
    if not role:
        return None
    role = role.strip()
    if role in ROLES:
        return role
    # 尝试别名映射
    for alias, canon in ROLES_ALIAS.items():
        if role == alias or role.endswith(alias):
            return canon
    # 无「架构·」前缀但核心名能匹配到 → 补前缀
    for canon in ROLES:
        if canon in role or role in canon:
            return canon
    return None


def _parse_repo_from_remote():
    """从 git remote 动态解析当前 org/repo（不写死）。"""
    try:
        out = os.popen("git config --get remote.origin.url 2>/dev/null").read()
        m = re.search(r"[:/]([\w.-]+/[\w.-]+?)(?:\.git)?\s*$", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    # 兜底：环境变量
    slug = os.environ.get("CNB_REPO_SLUG", "")
    if slug:
        return slug
    return ""


def check(text, role=None):
    """校验文本是否含完整 `@org/repo(角色)` + `[触发:<角色全称>]`。

    返回 (ok: bool, reasons: list)。缺任意标记 → ok=False + reasons 说明缺失项。
    """
    if not text:
        return False, ["文本为空，无任何接力标记"]
    reasons = []

    # ① @org/repo(角色) 完整召唤标记
    # 模式: @org/repo(角色)  例如 @dongdongxiaozu/dongjiagoushi(架构·评审)
    at_pattern = re.compile(r"@([\w.-]+/[\w.-]+)\(([^)]+)\)")
    at_hits = at_pattern.findall(text)
    if not at_hits:
        reasons.append(
            "缺少完整 `@org/repo(角色)` 召唤标记（如 `@dongdongxiaozu/dongjiagoushi(架构·评审)`）"
        )
    elif role is not None:
        target_role = _normalize_role(role)
        if target_role:
            matched = any(
                target_role in r for _, r in at_hits
                or target_role == _normalize_role(r) for _, r in at_hits
            )
            if not matched:
                reasons.append(
                    f"@ 标记未命中目标角色 `{target_role}`（当前含: "
                    + ", ".join(r for _, r in at_hits) + "）"
                )

    # ② [触发:<角色全称>] 显式声明触发标记（rules 最高优先）
    trigger_pattern = re.compile(r"\[触发:\s*([^]]+)\]")
    trigger_hits = trigger_pattern.findall(text)
    if not trigger_hits:
        reasons.append(
            "缺少 `[触发:<角色全称>]` 显式触发标记（AGENTS.md 触发强制化·① 最高优先）"
        )
    elif role is not None:
        target_role = _normalize_role(role)
        if target_role:
            matched = any(
                target_role in t or target_role == _normalize_role(t)
                for t in trigger_hits
            )
            if not matched:
                reasons.append(
                    f"[触发] 标记未命中目标角色 `{target_role}`（当前含: "
                    + ", ".join(t.strip() for t in trigger_hits) + "）"
                )

    # ③ 用 @CodeBuddy 而非完整 @org/repo(角色) 召唤协作角色 = 无效接力
    if "@CodeBuddy" in text and "@" in text:
        # 仅当存在 @CodeBuddy 但缺少完整 @org/repo(角色) 触发协作角色时提示
        if not at_hits:
            reasons.append(
                "检测到 `@CodeBuddy` 兜底召唤，但缺少完整 `@org/repo(角色)`；"
                "协作角色应显式 @ 其完整仓库角色，@CodeBuddy 不保证命中评审/开发等角色"
            )

    return not reasons, reasons


def check_required(text, role=None):
    """强制版校验：缺任意标记即抛 ValueError（供 CI 红灯拦截）。

    返回 True（校验通过）；不通过抛 ValueError 带 reasons。
    """
    ok, reasons = check(text, role=role)
    if not ok:
        raise ValueError("INVALID_RELAY: " + "；".join(reasons))
    return True


def gen(to_role, repo=None):
    """基于当前仓库动态生成合规接力卡 @ 模板（复用 HandleAbility 不写死）。

    to_role 可为规范全称或别名（如 '架构·评审' / '评审'）。
    返回带完整 `@org/repo(角色) [触发:角色]` 的合规接力文本。
    """
    canon = _normalize_role(to_role)
    if not canon:
        raise ValueError(f"无法识别目标角色 `{to_role}`，可用: {ROLES}")
    slug = repo or _parse_repo_from_remote() or os.environ.get("CNB_REPO_SLUG", "org/repo")
    return f"@{slug}({canon}) `[触发:{canon}]`"


def capability():
    """返回能力声明（供工具注册表 / 文档引用）。"""
    return {
        "name": "relay_card",
        "version": "v0.1.0",
        "module": "relay-card",
        "type": "工具·防断链校验",
        "desc": "接力卡触发强制校验：校验完整 @org/repo(角色) + [触发:角色全称]，缺失即拦截；动态生成合规接力卡模板",
        "interfaces": ["check", "check_required", "gen"],
        "deps": ["handle (HandleAbility)"],
        "usage": "交付/接力动作前调用 check 校验；用 gen 生成合规 @ 模板",
        "register": True,
    }
