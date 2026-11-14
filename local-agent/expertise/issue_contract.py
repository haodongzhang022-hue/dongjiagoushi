# -*- coding: utf-8 -*-
"""
Issue 唯一标题契约（issue_contract）
====================================
本模块解决用户点名的真实问题：**「之前弄了很多协作的 issue，很多其实名字不唯一，
有重复，也没真的启用」**。

根因不在人，而在**派发器没有约束**：任何调用方把自由文本当标题建 Issue，于是
「CLI控制台发起」「测试登录模块」被建了 8 次，「聚合页控制动作演示」7 次，
「云端开发请求：对齐登录模块PR产出」2 次 —— 名字不唯一、无法检索、没人认领。

本模块把「唯一」变成**结构性保证**，而不是事后人工去重：

  1. **标题 = 契约**：`<类型>:<模块> · <唯一键>`
       - 类型 ∈ FEAT/BUG/FIX/DOCS/CHORE/TEST/REL/RFC（限定集，不许自造）
       - 模块 ∈ MODULE_WHITELIST（推动模块/Agent 双版本管理，见 docs/ISSUE_MANAGEMENT.md）
       - 唯一键：稳定、可寻址、人可读，如 `expertise-pareto`、`issue-341`
  2. **唯一性由 (类型, 模块, 唯一 key) 三元组判定**（`issue_key`），标题只是它的
     渲染形态 —— 即使大小写/空格/标点漂移，也不会产生第二个 Issue；
  3. **幂等派发**（`plan`）：给定现有 Issue 清单 + 期望派发清单，产出
     create / reuse / duplicate(需收并) 三类动作，**绝不重复建**；
  4. **收并计划**（`dedupe_plan`）：把重复标题归并到「保留主号 + 关闭重复号」，
     并生成可核验的闭环注释文本；
  5. **反垃圾判据**（`is_low_signal`）：标题过短、纯测试串、与既有标题高度雷同的，
     在派发前就拦住（fail-fast，不让垃圾进仓库）。

设计纪律：本模块**只产出动作与证据**，不直接调用网络 —— 由 scripts 层执行，
保证本地可单测、可在演练（dry-run）模式下安全验证。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone

# 受限的类型集（与 ISSUE_MANAGEMENT.md 的类型对齐；不许自造）
ISSUE_TYPES = ("FEAT", "BUG", "FIX", "DOCS", "CHORE", "TEST", "REL", "RFC")

# 模块白名单：推动模块/Agent 双版本管理，新模块须先登记（加行 + 建正文）
MODULE_WHITELIST = (
    "expertise",        # 专家级架构能力（七维/帕累托/前沿/时效）
    "external-validation",  # 功能性代码验证门禁
    "issue-contract",   # Issue 唯一标题契约
    "local-agent",
    "platform-adapter",
    "secretary",
    "manager",
    "architect",
    "reviewer",
    "tester",
    "deliverer",
    "data-layer",
    "collab",
    "dispatcher",
    "sentinel",
    "topology",
    "dev-standard",
    "label",
    "depth",
    "dispatch",
    "handle",
    "scale",
    "hybrid",
    "memory",
    "dsh-adapter",
)

# 唯一键合法字符：小写字母数字，用 - . _ 连接（稳定性优先，禁止中文/空格/标点）
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,60}$")

# 时间敏感标记：带"当前/最新/即将"等字样的标题说明写的是易过期断言，须注明日期
_TIME_SENSITIVE_RE = re.compile(r"(最新|当前|目前|即将|不久|今年|本月|最近|nowadays|latest)")

# 低信号标题特征（垃圾/测试流）
_LOW_SIGNAL_EXACT = {
    "test", "test1", "测试", "demo", "试验", "临时", "todos", "todo", "1", "aaa",
    "untitled", "无标题", "hello", "asdf", "qwerty",
}
_LOW_SIGNAL_PATTERNS = (
    r"^cl[\u4e00-\u9fa5]{0,6}控制台发起$",     # 「CLI控制台发起」
    r"^聚合页控制动作演示$",
    r"^(测试|评审|开发|上线)登录模块$",
    r"^(测试|test)[-_]?\d*$",
    r"^.{0,2}$",                              # 1~2 字标题
)

# 低信号**唯一键**的精确命中（占位型 key —— 不是子串匹配，避免误伤 p0-latency 之类）
_LOW_SIGNAL_KEYS = {
    "p0", "p1", "p2", "p3", "t0", "t1", "tmp", "temp", "todo", "tbd", "dummy",
    "test", "test1", "demo", "sample", "foo", "bar", "baz", "x", "xx", "xxx",
    # 关键字型残片：中文标题被剔掉后只剩这些英文词时，它代表不了原意，不能当唯一键
    # （`fix 登录` / `fix 支付` 都塌成 `fix` → 两件事被静默并成一件事）
    "pr", "mr", "fix", "bug", "feat", "docs", "chore", "patch", "issue",
    "api", "cli", "ui", "web", "app", "dev", "run", "new", "old", "work", "code",
}

TITLE_TEMPLATE = "{type}:{module} · {key}"


def _now():
    return datetime.now(timezone.utc).isoformat()


def normalize(text):
    """归一化：全角转半角、去多余空白、统一大小写 —— 抗「看起来不同其实相同」。"""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_title(issue_type, module, key):
    """按契约生成标题；任何字段非法即报错（不给「差不多」留余地）。"""
    itype = (issue_type or "").strip().upper()
    if itype not in ISSUE_TYPES:
        raise ValueError(f"Issue 类型必须是 {ISSUE_TYPES} 之一，实际 {issue_type!r}")
    mod = (module or "").strip().lower()
    if mod not in MODULE_WHITELIST:
        raise ValueError(f"模块 {module!r} 未在白名单；新模块须先登记 MODULE_WHITELIST")
    k = (key or "").strip().lower()
    if not _KEY_RE.match(k):
        raise ValueError(
            f"唯一键 {key!r} 非法：只允许小写字母/数字与 - . _，长度 2-61"
        )
    return TITLE_TEMPLATE.format(type=itype, module=mod, key=k)


def issue_key(title):
    """把任意标题解析为唯一三元组 key；不符合契约返回 None（而非猜测）。"""
    text = normalize(title)
    match = re.match(r"^\s*([A-Za-z]+)\s*:\s*([A-Za-z0-9_.-]+)\s*[·•]\s*(.+?)\s*$", text)
    if not match:
        return None
    itype, module, key = match.group(1).upper(), match.group(2).lower(), match.group(3).lower()
    if itype not in ISSUE_TYPES or module not in MODULE_WHITELIST:
        return None
    if not _KEY_RE.match(key):
        return None
    return f"{itype}:{module}:{key}"


def is_low_signal(title):
    """判断标题是否为低信号（测试流/占位/过短）。返回 (bool, reason)。

    判据分两层：
      1. **整条标题**像占位（「测试登录模块」「聚合页控制动作演示」）→ 拦；
      2. 标题合契约时，再看**唯一键**是否本身是占位词（`p0`/`tmp`/`todo`）→ 拦。
    注：唯一键出现 test 字样本身不是问题（`test-first-gate` 是有意义的键），
    只有**整键就是占位词**才拦 —— 子串匹配会误伤正常键。
    """
    text = normalize(title)
    if not text:
        return True, "标题为空"
    low = text.lower()
    if low in _LOW_SIGNAL_EXACT:
        return True, f"占位型标题：{text!r}"
    key = issue_key(text)
    if key is None:
        for pattern in _LOW_SIGNAL_PATTERNS:
            if re.match(pattern, text, flags=re.IGNORECASE):
                return True, f"测试流标题特征命中 /{pattern}/：{text!r}"
        return True, "不符合唯一标题契约 <类型>:<模块> · <唯一键>"
    unique_key = key.rsplit(":", 1)[-1]
    if unique_key in _LOW_SIGNAL_KEYS:
        return True, f"唯一键是占位词：{unique_key!r}（须用可寻址的稳定键）"
    return False, ""


def similarity(a, b):
    """标题相似度 0~1（字符 2-gram 归一化），用于识别「换汤不换药」的近重复。"""
    na, nb = normalize(a).lower(), normalize(b).lower()
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    def grams(s):
        if len(s) < 2:
            return {s}
        return {s[i:i + 2] for i in range(len(s) - 1)}
    ga, gb = grams(na), grams(nb)
    if not ga or not gb:
        return 0.0
    return round(len(ga & gb) / len(ga | gb), 4)


def _stable_digest(text):
    return hashlib.sha256(normalize(text).lower().encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 一、幂等派发计划
# ---------------------------------------------------------------------------
def plan(desired, existing, similarity_threshold=0.9):
    """计算派发计划（幂等：同 key 绝不重复建）。

    desired : [{type, module, key, body?}] 或 [{title: ...}]（title 须合契约）
    existing: [{number, title, state?}] 现有 Issue（含已关闭）

    返回：
      {create: [...], reuse: [...], duplicates: [...], rejected: [...],
       by_key: {...}, generated_at}
    """
    existing = existing or []
    # 建立 现有 key 索引（同一 key 多个号码 = 重复，须收并）
    by_key = {}
    for issue in existing:
        key = issue_key(issue.get("title", ""))
        if not key:
            continue
        by_key.setdefault(key, []).append({
            "number": str(issue.get("number")),
            "title": issue.get("title"),
            "state": issue.get("state", "open"),
        })

    create, reuse, duplicates, rejected = [], [], [], []
    for item in desired or []:
        try:
            if item.get("title"):
                title = normalize(item["title"])
                key = issue_key(title)
                if key is None:
                    raise ValueError(f"标题不符合契约：{title!r}")
            else:
                title = build_title(item.get("type"), item.get("module"), item.get("key"))
                key = issue_key(title)
        except ValueError as exc:
            rejected.append({"input": item, "reason": str(exc)})
            continue

        low, why = is_low_signal(title)
        if low:
            # 低信号只拦「新建」，若已存在同 key 仍允许 reuse（历史遗留）
            if key not in by_key:
                rejected.append({"input": item, "title": title, "reason": why})
                continue

        hits = by_key.get(key) or []
        if not hits:
            create.append({
                "key": key,
                "title": title,
                "body": item.get("body", ""),
                "idempotency_token": _stable_digest(key),
            })
            # 同一批 desired 内也不允许重复
            by_key.setdefault(key, []).append({"number": None, "title": title, "state": "new"})
        else:
            open_hits = [h for h in hits if h.get("state", "open") == "open"]
            target = open_hits[0] if open_hits else hits[0]
            reuse.append({
                "key": key,
                "title": title,
                "reuse_number": target.get("number"),
                "reuse_state": target.get("state"),
                "note": "已存在同 key Issue，复用不再新建",
            })
            if len(hits) > 1:
                duplicates.append({
                    "key": key,
                    "title": title,
                    "numbers": [h.get("number") for h in hits],
                })

    # 近重复检测（不同 key 但标题高度相似 → 人复核收并，不自动合并语义）
    all_titles = [{"number": str(i.get("number")), "title": i.get("title", "")} for i in existing]
    near = []
    for i in range(len(all_titles)):
        for j in range(i + 1, len(all_titles)):
            sim = similarity(all_titles[i]["title"], all_titles[j]["title"])
            if sim >= similarity_threshold:
                near.append({
                    "a": all_titles[i]["number"], "b": all_titles[j]["number"],
                    "similarity": sim,
                    "titles": [all_titles[i]["title"], all_titles[j]["title"]],
                })
    return {
        "create": create,
        "reuse": reuse,
        "duplicates": duplicates,
        "near_duplicates": near,
        "rejected": rejected,
        "by_key": {k: v for k, v in by_key.items()},
        "generated_at": _now(),
    }


# ---------------------------------------------------------------------------
# 二、收并计划（重复 → 保留主号，关闭重复号）
# ---------------------------------------------------------------------------
def dedupe_plan(existing, prefer="oldest", similarity_threshold=0.9):
    """生成重复标题的收并计划。

    返回：
      {groups: [{title, numbers, keep, close: [...], comment}], unchanged: count}
    """
    groups = {}
    for issue in existing or []:
        title = normalize(issue.get("title", ""))
        if not title:
            continue
        groups.setdefault(title, []).append({
            "number": str(issue.get("number")),
            "comments": int(issue.get("comment_count") or 0),
            "state": issue.get("state", "open"),
        })

    plans = []
    for title, items in groups.items():
        if len(items) < 2:
            continue
        # 选保留者：默认保留最小编号（最早，可追溯）；可改为保留评论最多者
        if prefer == "most_comments":
            items_sorted = sorted(items, key=lambda x: (-x["comments"], int(x["number"])))
        else:
            items_sorted = sorted(items, key=lambda x: int(x["number"]))
        keep = items_sorted[0]
        close = [x["number"] for x in items_sorted[1:]]
        comment = (
            f"## 收并通知（唯一标题契约 · issue-contract）\n\n"
            f"本 Issue 与 #{keep['number']} 标题重复（`{title}`），按唯一标题契约归并到 "
            f"#{keep['number']} 继续跟进。\n\n"
            f"- 归并规则：同一标题只保留一个主号，其余关闭并回指主号\n"
            f"- 主号：#{keep['number']}（评论数 {keep['comments']}）\n"
            f"- 关闭：{', '.join('#' + n for n in close)}\n"
            f"- 后续请统一在 #{keep['number']} 讨论，避免信息分叉\n"
            f"- 契约文档：`docs/ISSUE_CONTRACT.md`\n"
        )
        plans.append({
            "title": title,
            "numbers": [x["number"] for x in items],
            "keep": keep["number"],
            "close": close,
            "comment": comment,
        })

    # 近重复（不同标题但几乎相同）单独列出供人工判断
    near = plan([], existing, similarity_threshold=similarity_threshold).get("near_duplicates", [])
    return {
        "groups": plans,
        "near_duplicates": near,
        "unchanged": len(groups) - len(plans),
        "generated_at": _now(),
    }


# ---------------------------------------------------------------------------
# 三、Issue 正文契约（agent-ready brief · 对齐 docs/ISSUE_TRACKING.md）
# ---------------------------------------------------------------------------
REQUIRED_SECTIONS = (
    "目标", "做/不做边界", "验收标准", "外部验证", "信息来源与时效",
)


def validate_body(body):
    """校验 Issue 正文是否满足 agent-ready brief 最小契约。返回 (ok, missing)。"""
    text = body or ""
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    return (not missing), missing


def build_body(*, objective, in_scope, out_of_scope, acceptance, verification,
               sources=None, module_version="", agent_version="", depends_on=""):
    """按契约生成 agent-ready 的 Issue 正文（含双版本声明头）。"""
    src_lines = []
    for item in sources or []:
        src_lines.append(
            f"- {item.get('kind', 'unknown')}｜{item.get('source', '')}"
            f"｜dated_at={item.get('dated_at', '')}"
        )
    if not src_lines:
        src_lines.append("- （待补：任何事实都必须带来源与日期，否则不得作为决策依据）")
    ver_lines = []
    if module_version:
        ver_lines.append(f"- module_version: {module_version}")
    if agent_version:
        ver_lines.append(f"- agent_version: {agent_version}")
    if depends_on:
        ver_lines.append(f"- depends_on: {depends_on}")
    return (
        f"## 目标\n{objective}\n\n"
        f"## 做/不做边界\n"
        f"- 做：\n" + "\n".join(f"  - {x}" for x in (in_scope or ["（待补）"])) + "\n"
        f"- 不做：\n" + "\n".join(f"  - {x}" for x in (out_of_scope or ["（待补）"])) + "\n\n"
        f"## 验收标准\n" + "\n".join(f"- [ ] {x}" for x in (acceptance or ["（待补）"])) + "\n\n"
        f"## 外部验证\n"
        f"- 功能性代码验证（真实执行，非静态检查）：\n"
        + "\n".join(f"  - [ ] `{x}`" for x in (verification or ["（待补）"])) + "\n\n"
        f"## 信息来源与时效\n" + "\n".join(src_lines) + "\n\n"
        f"## 版本声明\n" + ("\n".join(ver_lines) if ver_lines else "- （待补双版本声明）") + "\n"
    )


# ---------------------------------------------------------------------------
# 四、派发前闸门（接线层：把契约真正挂到「建 Issue」这一步上）
# ---------------------------------------------------------------------------
# 为什么需要这一层：`plan()/dedupe_plan()` 只是**纯计算**，谁不调它谁就绕过契约。
# 2026-11-14 实测就是这样——专家层与契约都合进 main 了，可 `dispatch_engine` /
# `entries.cnb_live` 建 Issue 时仍然直接用自由文本当标题，于是同一天又长出
# `开发登录模块 / 评审登录模块 / 测试登录模块` 三条。**契约不接线 = 不生效。**
# 本层 `guard_create()` 是派发器唯一入口：给「想用的标题」，它返回
# create（含契约化后的标题）/ reuse（已有同 key，别再建）/ reject（无法契约化）。

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# 有效字符：字母数字 + 中日韩文字（算"被 ascii 丢弃的实质内容"）
_ALNUM_RE = re.compile(r"[0-9a-z]|[\u4e00-\u9fff]|\u3040-\u30ff|\uac00-\ud7af")


def _ascii_coverage(text):
    """ascii 字符占原文有效字符的比例（0~1）。中文被整段剔掉时这个值会明显 <1。"""
    effective = _ALNUM_RE.findall(normalize(text).lower())
    if not effective:
        return 0.0
    return sum(1 for ch in effective if ch.isascii()) / float(len(effective))


def slugify_key(text, seed=""):
    """把任意文本压成合法唯一键；**绝不因为"好看"牺牲唯一性**。

    规则（每条都对应一个真实事故）：
      1. 纯 ascii 且不是关键字 → 直接用，可读优先（`refactor-login-module`）；
      2. 有内容被丢掉（中文/日文被整段剔掉）→ 可读残片 **+ 内容摘要后缀**，
         例如 `update-readme-3f2a1b9c`：既保留人可读线索，又保证两件不同的事
         不会共用一个键（第一版只留残片，`API 接口改造` / `登录模块 API` /
         `开发登录模块 API` 全塌成 `api`，第二条诉求过闸门直接被并进第一条）；
      3. 残片本身是关键字（`fix`/`pr`/`api`/`todo`…）或压根没有 ascii → 纯摘要。
    同一段文本永远压出同一个键（幂等的根），不同文本永远压出不同键（不吞任务）。
    """
    normalized = normalize(text).lower()
    raw_ascii = _SLUG_RE.sub("-", normalized).strip("-")
    raw_ascii = re.sub(r"-{2,}", "-", raw_ascii)
    ascii_part = raw_ascii[:48].strip("-")
    usable = (ascii_part and ascii_part[0].isalnum() and len(ascii_part) >= 2
              and ascii_part not in _LOW_SIGNAL_KEYS)
    if usable:
        # 「残片就是全部内容」有两个条件，缺一就会吞任务：
        #   ① 覆盖率 1.0（没被剔掉中文）；② **没被截断**（≤48 字符）。
        # 第一版只判①，纯英文长标题截到 48 字符后直接返回残片，第 48 字符之后的
        # 内容不参与唯一性 —— 实测 `...pipeline stage one/two` 压出同一个键，
        # 第二条诉求被 reuse 进第一条的 Issue（比原来的重复更糟：两件事并成一件）。
        if _ascii_coverage(normalized) >= 0.999 and len(raw_ascii) <= 48:
            return ascii_part
        # 有实质内容被丢弃：残片只当"读得懂的线索"，唯一性由摘要后缀保证
        return "%s-%s" % (ascii_part[:38].strip("-"), _stable_digest(seed or text)[:8])
    return "task-" + _stable_digest(seed or text)


def derive_title(text, *, module="local-agent", issue_type="CHORE", seed=""):
    """把不合格的标题**契约化**（保住唯一与幂等，不丢信息——原文进正文）。"""
    return build_title(issue_type, module, slugify_key(text, seed=seed or text))


def guard_create(title, existing=None, *, module="local-agent",
                 issue_type="CHORE", seed="", derive=True):
    """建 Issue 前唯一闸门：返回 create / reuse / reject，**永不返回原始垃圾标题**。

    title    : 调用方想用的标题（可以是自由文本）
    existing : [{number, title, state?}] 现有 Issue（含已关闭）
    derive   : True=不合格标题自动契约化（保住幂等）；False=直接 reject

    返回 {action, title, original, reason, derived, reuse_number, key}
    """
    original = normalize(title)
    existing = existing or []
    by_key = {}
    by_literal = {}
    for issue in existing:
        t = issue.get("title", "")
        k = issue_key(t)
        if k:
            by_key.setdefault(k, []).append(issue)
        # 存量里不合契约的脏标题（`开发登录模块`）也要能挡同名重复：
        # 那正是「同一天长出三条一模一样 Issue」的真实成因，只按契约 key 匹配挡不住。
        if normalize(t):
            by_literal.setdefault(normalize(t).lower(), []).append(issue)

    def _reuse_of(hits, candidate, derived, extra_reason):
        open_hits = [h for h in hits if (h.get("state") or "open") == "open"]
        target = (open_hits or hits)[0]
        return {
            "action": "reuse", "title": candidate, "original": original,
            "key": issue_key(candidate), "derived": derived,
            "reuse_number": str(target.get("number")),
            "matched_title": target.get("title") or "",
            "reason": (extra_reason + "；" if extra_reason else "")
                      + f"已存在同 key Issue #{target.get('number')}，复用不再新建",
        }

    def _decide(candidate, derived, extra_reason=""):
        key = issue_key(candidate)
        hits = by_key.get(key) or []
        open_hits = [h for h in hits if (h.get("state") or "open") == "open"]
        target = (open_hits or hits or [None])[0]
        if target is not None:
            return {
                "action": "reuse", "title": candidate, "original": original,
                "key": key, "derived": derived, "reuse_number": str(target.get("number")),
                "matched_title": target.get("title") or "",
                "reason": (extra_reason + "；" if extra_reason else "")
                          + f"已存在同 key Issue #{target.get('number')}，复用不再新建",
            }
        return {
            "action": "create", "title": candidate, "original": original,
            "key": key, "derived": derived, "reuse_number": None,
            "reason": extra_reason or "符合唯一标题契约",
        }

    if not original:               # 空标题没有原文可摘要，契约化也救不回来 → 明确拒绝
        return {"action": "reject", "title": "", "original": original, "key": None,
                "derived": False, "reuse_number": None, "reason": "标题为空"}

    # ① 原文同名已存在（含合不上契约的存量脏标题）→ 直接复用，不再新建
    same = by_literal.get(original.lower()) or []
    if same:
        return _reuse_of(same, same[0].get("title") or original, derived=False,
                         extra_reason=f"原文同名 Issue 已存在（标题 {original!r}）")

    low, why = is_low_signal(original)
    if not low:
        return _decide(original, derived=False)

    if not derive:
        return {"action": "reject", "title": "", "original": original, "key": None,
                "derived": False, "reuse_number": None, "reason": why}

    seed = seed or original
    try:
        derived_title = derive_title(original, module=module, issue_type=issue_type,
                                     seed=seed)
    except ValueError as exc:      # 类型/模块/键非法 → 无法契约化，明确拒绝
        return {"action": "reject", "title": "", "original": original, "key": None,
                "derived": False, "reuse_number": None,
                "reason": f"原标题不合格（{why}）且无法契约化：{exc}"}

    # derive 之后必须**再复核一次**：第一版漏了这步，`p0`/`tmp` 这类占位词当唯一键
    # 被 `is_low_signal` 明确判为低信号，却能原样放行（`_LOW_SIGNAL_KEYS` 在这条分支失效）。
    low2, why2 = is_low_signal(derived_title)
    if low2:
        digest_title = build_title(issue_type, module,
                                   "task-" + _stable_digest(seed + "#retry"))
        low3, why3 = is_low_signal(digest_title)
        if low3:
            return {"action": "reject", "title": "", "original": original, "key": None,
                    "derived": False, "reuse_number": None,
                    "reason": f"原标题不合格（{why}），契约化后仍不合格：{why3}"}
        return _decide(digest_title, derived=True,
                       extra_reason=(f"原标题不合格（{why}）→ 契约化结果仍不合格"
                                     f"（{why2}）→ 改用摘要键 {digest_title!r}"))
    return _decide(derived_title, derived=True,
                   extra_reason=f"原标题不合格（{why}）→ 契约化为 {derived_title!r}")
