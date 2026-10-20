# -*- coding: utf-8 -*-
"""
承接侧核心（intent.take · module inbound-take v0.1.1）
======================================================
云端接件 → 判承接 → 出承接卡 → 出交接单（本地跑）→ 本地回收核对 → 结论留痕。

一切判定都是**确定性代码**（不靠 LLM 感觉），输入相同输出相同：
  - `judge()`     按任务 kind + runtime 判「接得住 / 半承接 / 拒接」，拒接必带替代；
  - `verify()`    按验收标准逐条核对本地回传结果，缺项即拒收（不吞异常）；
  - `tally()`     汇总批扫三态（delivered / stuck / rejected），给人类俯瞰用。

诚实性硬约束：`ran_remotely` 恒为 False——云端没跑过的不许写成跑过。
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

__all__ = ["TASK_KINDS", "RUNTIMES", "make_card", "judge", "handoff", "collect",
           "verify", "render_md", "tally", "capability", "ledger"]

MODULE = "inbound-take"
VERSION = "v0.1.1"

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ledger")
_LEDGER_FILE = os.path.join(STATE_DIR, "cards.json")

# 任务类型 → 承接画像。exec=必须本地运行时；deliverable=默认交付形态
TASK_KINDS = {
    "code":     {"exec": "local", "deliverable": "patch",  "desc": "写码/改动"},
    "test":     {"exec": "local", "deliverable": "report", "desc": "跑测试/信号灯"},
    "review":   {"exec": "cloud", "deliverable": "report", "desc": "评审/走查"},
    "doc":      {"exec": "cloud", "deliverable": "patch",  "desc": "文档/索引"},
    "design":   {"exec": "cloud", "deliverable": "doc",    "desc": "方案/架构"},
    "research": {"exec": "cloud", "deliverable": "report", "desc": "调研/素材"},
    "ops":      {"exec": "cloud", "deliverable": "report", "desc": "派发/编排/协调"},
    "unknown":  {"exec": "unknown", "deliverable": "report", "desc": "未分类"},
}

# 运行时归属：本地电脑跑 / 云端跑（云端只承接，不跑业务）
RUNTIMES = {
    "local": {"label": "用户本地电脑", "can_exec": True},
    "cloud": {"label": "云端承接端", "can_exec": False},
}

# 承接状态
STATUS_OPEN = "accepted"          # 已接，等本地 runtime 执行
STATUS_DELIVERED = "delivered"    # 本地回传且验收通过
STATUS_STUCK = "stuck"            # 接了但没收件/超期未回传
STATUS_REJECTED = "rejected"      # 明确拒接（带替代动作）


UNVERIFIED_MARK = "（未验证，须本地跑通才算完）"


def _unverified(deliverable):
    """半承接交付形态：强制带「未验证」标记。

    云端不跑运行时，出的补丁/计划一律没验证过——这个标记是事实，不是可选措辞，
    不能被调用方用 deliverable 入参覆盖掉（否则一句"patch（已验证）"就把边界抹了）。
    """
    text = str(deliverable or "").strip() or "patch"
    if "未验证" in text:
        return text
    return text + UNVERIFIED_MARK


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir():
    os.makedirs(STATE_DIR, exist_ok=True)


def _load():
    """读账本。坏文件**不静默吞**：改名 .bad 留证后重开空账本（否则下次 _save 直接覆盖 = 历史承接卡全丢）。"""
    if not os.path.exists(_LEDGER_FILE):
        return {}
    try:
        with open(_LEDGER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        bad = _LEDGER_FILE + ".bad"
        try:
            os.replace(_LEDGER_FILE, bad)
        except OSError:
            bad = _LEDGER_FILE
        print(f"[inbound-take] 账本损坏（{type(e).__name__}: {e}），已另存 {bad}，"
              f"本次从空账本重开——请人工确认历史承接卡", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        bad = _LEDGER_FILE + ".bad"
        try:
            os.replace(_LEDGER_FILE, bad)
        except OSError:
            bad = _LEDGER_FILE
        print(f"[inbound-take] 账本结构非法（非 dict），已另存 {bad}", file=sys.stderr)
        return {}
    return data


def _save(data):
    _ensure_dir()
    with open(_LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _seq(name, value):
    """列表型入参严格校验：只收 list/tuple，**拒绝字符串按字符拆开**（静默错会毁掉验收判定）。

    S01 错误处理不吞异常：`acceptance='有文档'` 这种传参以前会被拆成 ['有','文','档']，
    三条验收各自去 evidence 匹配单字、静默判通过——现在直接 ValueError 说清楚。
    """
    if value is None:
        return []
    if isinstance(value, str):
        raise ValueError(
            f"{name} 须传列表（如 ['信号灯全绿']），收到字符串 {value!r}——"
            f"按字符拆开会静默破坏验收判定，故显式拒绝")
    if not isinstance(value, (list, tuple)):
        raise TypeError(
            f"{name} 须传 list/tuple，收到 {type(value).__name__}（{value!r}）")
    return [str(v).strip() for v in value if str(v).strip()]


_ISSUE_NO_RE = None


def _issue_no(value):
    """从 `issue#177` / `#177` / `177` / PR 链接里抽出纯编号，抽不出返回空串。"""
    global _ISSUE_NO_RE
    if _ISSUE_NO_RE is None:
        _ISSUE_NO_RE = re.compile(r"(?:#|^(?:issue|issues|pull|pulls)[/:#-]?)\s*(\d+)", re.I)
    m = _ISSUE_NO_RE.search(str(value or "").strip())
    if m:
        return m.group(1)
    return ""


def _card_id(title, origin):
    """承接卡 id：同一 (来源, 标题) 稳定不漂移，二次触发取回同一张卡。"""
    import hashlib
    raw = (str(origin) + "::" + str(title)).encode("utf-8")
    return "ib-" + hashlib.sha1(raw).hexdigest()[:12]


# ---------------------------------------------------------------------------
# 一、承接判定：接得住？接一半？接不了说清楚
# ---------------------------------------------------------------------------
def judge(kind="unknown", runtime="local", deliverable=None):
    """按任务类型 + 运行时判承接方式（确定性，报第一个不成立的理由）。

    返回：
      accept      True=接；False=拒接
      mode        full（全套，含代码改动）/ partial（只出方案+判定标准）/
                  reject（接不了，需换承接方）
      deliverable 实际交付形态（半承接强制追加「未验证」标记，不可被入参覆盖）
      reasons     判定理由（人可读）
      alternative 拒接时的替代动作（拒接必须给，不静默吞件）
    """
    k = (kind or "unknown").strip().lower()
    spec = TASK_KINDS.get(k, TASK_KINDS["unknown"])
    rt = RUNTIMES.get((runtime or "local").strip().lower())
    reasons = []

    if not rt:
        return {"accept": False, "mode": "reject", "deliverable": None,
                "reasons": [f"未知运行时 `{runtime}`（可用: {', '.join(RUNTIMES)}）"],
                "alternative": "指定运行时归属（本地电脑 / 云端承接端）后重发"}

    if rt["can_exec"]:
        # 本地运行时：能跑就能接，交付形态按任务类型
        dv = deliverable or spec["deliverable"]
        reasons.append(f"{spec['desc']} 由 {rt['label']} 执行，交付形态 = {dv}")
        return {"accept": True, "mode": "full", "deliverable": dv,
                "reasons": reasons, "alternative": None}

    # 云端承接端：不跑业务，只承接不执行的活
    if k in ("review", "doc", "design", "research", "ops"):
        dv = deliverable or spec["deliverable"]
        reasons.append(f"{spec['desc']} 不需要真跑运行时，云端承接端可直接做，交付形态 = {dv}")
        return {"accept": True, "mode": "full", "deliverable": dv,
                "reasons": reasons, "alternative": None}

    if k in ("code", "test"):
        reasons.append(f"{spec['desc']} 必须由本地运行时执行（云端建环境贵，见 CLOUD_LOCAL_COOP.md）")
        reasons.append("云端只承接：出改动方案/补丁 + 验收标准，代码与测试结果由本地跑出来")
        dv = _unverified(deliverable or spec["deliverable"])
        reasons.append(f"交付形态 = {dv}（未验证标记为强制，不可被入参覆盖）")
        return {"accept": True, "mode": "partial",
                "deliverable": dv,
                "reasons": reasons,
                "alternative": "本地 runtime 跑通后回传，云端按验收标准核对并收口"}

    reasons.append(f"任务类型未知（{k}），无法判定承接边界")
    return {"accept": False, "mode": "reject", "deliverable": None,
            "reasons": reasons,
            "alternative": "补 kind（code/test/review/doc/design/research/ops）后再发"}


# ---------------------------------------------------------------------------
# 二、承接卡：接了哪件活、按什么形态交、验什么才算完
# ---------------------------------------------------------------------------
def make_card(title, origin="issue", kind="unknown", runtime="local",
              acceptance=None, scope_done=None, scope_not=None,
              deliverable=None, input_ref="", parent_issue="", owner="CodeBuddy"):
    """生成一张承接卡（承接凭证）。字段命名对齐 OSS 提交模板习惯：
    scope_done / scope_not（做/不做）/ acceptance（验收）/ runtime（谁跑）。

    返回 card dict，并写入本地账本（同 (origin,title) 幂等，取回同一张）。
    """
    if not title or not str(title).strip():
        raise ValueError("title 必填：承接卡必须说清接的是哪件活")
    acceptance = _seq("acceptance", acceptance)
    if not acceptance:
        raise ValueError(
            "acceptance 必填：没有验收标准就不算承接得住（退回补标准）")
    scope_done = _seq("scope_done", scope_done)
    scope_not = _seq("scope_not", scope_not)

    decision = judge(kind=kind, runtime=runtime, deliverable=deliverable)
    cid = _card_id(title, origin)
    cards = _load()
    prev = cards.get(cid)
    now = _now()
    card = {
        "card_id": cid,
        "title": str(title).strip(),
        "origin": origin,
        "parent_issue": _issue_no(parent_issue or origin) or str(parent_issue or origin),
        "kind": (kind or "unknown").lower(),
        "runtime": (runtime or "local").lower(),
        "owner": owner,
        "input_ref": input_ref,
        "decision": {
            "accept": decision["accept"],
            "mode": decision["mode"],
            "deliverable": decision["deliverable"],
            "reasons": decision["reasons"],
            "alternative": decision["alternative"],
        },
        "scope_done": scope_done,
        "scope_not": scope_not,
        "acceptance": acceptance,
        "status": STATUS_OPEN if decision["accept"] else STATUS_REJECTED,
        "ran_remotely": False,          # 诚实性硬约束：云端从不假装跑过
        "handoff": None,
        "receipt": None,
        "created_at": prev.get("created_at") if prev else now,
        "updated_at": now,
    }
    cards[cid] = card
    _save(cards)
    return card


def load_card(card_id):
    return _load().get(card_id)


def ledger(status=None):
    cards = _load()
    if status:
        return {k: v for k, v in cards.items() if v.get("status") == status}
    return cards


# ---------------------------------------------------------------------------
# 三、交接单：把活交给本地 runtime，云端不假装执行
# ---------------------------------------------------------------------------
def handoff(card, runtime="local", entry_cmd=None):
    """把承接卡落成交接单，交本地 runtime 执行。

    云端返回的是「交接契约 + 待执行动作」，`ran_remotely` 恒 False——
    没跑就是没跑，不许拿"已派发"冒充"已跑过"。
    """
    card_id = card["card_id"] if isinstance(card, dict) else card
    cards = _load()
    c = cards.get(card_id)
    if not c:
        return {"ok": False, "error": f"承接卡不存在: {card_id}"}
    if not c["decision"]["accept"]:
        return {"ok": False, "error": "该卡已判定拒接，不能出交接单",
                "alternative": c["decision"].get("alternative")}

    steps = _plan_steps(c, entry_cmd)
    job = {
        "job_id": "job-" + card_id,
        "card_id": card_id,
        "runtime": runtime or c["runtime"],
        "owner": c["owner"],
        "kind": c["kind"],
        "deliverable": c["decision"]["deliverable"],
        "steps": steps,
        "acceptance": list(c["acceptance"]),
        "expect_receipt": {
            "provide": ["changed_files", "test_output", "evidence"],
            "acceptance_report": list(c["acceptance"]),
        },
        "ran_remotely": False,
        "state": "awaiting_local_run",
        "issued_at": _now(),
    }
    c["handoff"] = job
    c["updated_at"] = _now()
    cards[card_id] = c
    _save(cards)
    return {"ok": True, "job": job}


def _plan_steps(card, entry_cmd):
    """交接单步骤：只给动作清单，不给伪造结果。"""
    steps = [{"n": 1, "do": f"本地 checkout 对应分支，按「做」清单实施：{card['scope_done'] or ['见承接卡']}"}]
    if card["kind"] in ("test",):
        steps.append({"n": 2, "do": "本地跑相关信号灯脚本，保留完整 stdout（不裁剪、不摘录）"})
    elif card["kind"] in ("code", "doc"):
        steps.append({"n": 2, "do": "本地跑变更相关测试/信号灯，保留完整 stdout"})
    if entry_cmd:
        steps.append({"n": len(steps) + 1, "do": f"入口命令: {entry_cmd}"})
    steps.append({"n": len(steps) + 1,
                  "do": "回传：changed_files / test_output / evidence（逐条对齐验收标准）"})
    return steps


# ---------------------------------------------------------------------------
# 四、本地回传 → 按验收标准核对（缺项即拒收，不吞异常）
# ---------------------------------------------------------------------------
def verify(card, result):
    """逐条核对本地回传是否满足验收标准。

    验收标准判定规则（确定性）：
      - 标准含「测试/信号灯/跑」→ 见 `_judge_test_output()`：要有合格信号
        （统一收尾 `N 通过 / M 失败` 且 M=0），**输不出合格信号即判不通过**，
        绝不因"没写失败"就默认绿；
      - 标准含「文件/模块/PR/补丁」→ 要有 changed_files；
      - 其他一律要求有 evidence 里对上该项的键或文本命中关键词。
    返回 (ok: bool, report: list[{criterion, ok, why}])。
    """
    acceptance = card.get("acceptance") or []
    result = result or {}
    test_output = str(result.get("test_output") or "")
    changed = result.get("changed_files") or []
    evidence = result.get("evidence") or {}
    evidence_text = json.dumps(evidence, ensure_ascii=False) if evidence else ""

    report = []
    for crit in acceptance:
        c = str(crit)
        hit = False
        why = ""
        if any(w in c for w in ("测试", "信号灯", "跑", "回归")):
            verdict = _judge_test_output(test_output)
            hit, why = verdict["ok"], verdict["why"]
        elif any(w in c for w in ("文件", "模块", "PR", "补丁", "改动")):
            hit = bool(changed)
            why = "有改动文件清单" if hit else "缺 changed_files"
        else:
            key_hit = any(str(k) in c or c in str(k) for k in (evidence or {}))
            text_hit = bool(evidence_text) and any(
                seg and seg in evidence_text for seg in _keywords(c))
            hit = key_hit or text_hit
            why = "evidence 命中该验收项" if hit else "evidence 未覆盖该验收项"
        report.append({"criterion": c, "ok": hit, "why": why})
    return all(r["ok"] for r in report), report


_FAIL_COUNT_RE = None
_PASS_COUNT_RE = None

def _fail_count(text):
    """识别仓库信号灯的统一收尾格式 `N 通过 / M 失败`，取 M。

    只认「数字 + 失败/不通过/✗」的计数写法；正文里出现「失败」二字不算失败
    （否则 `0 失败` 这种全绿收尾会被误判为不通过）。
    """
    global _FAIL_COUNT_RE
    if _FAIL_COUNT_RE is None:
        _FAIL_COUNT_RE = re.compile(r"(\d+)\s*(?:条|个)?\s*(?:失败|不通过)")
    hits = [int(m) for m in _FAIL_COUNT_RE.findall(text or "")]
    return max(hits) if hits else 0


def _pass_count(text):
    """统一收尾里的通过计数：`N 通过` / `N passed` / `PASS=97`；没有返回 None。

    只认**带数字**的通过计数——`ok all pass` / `all PASS` 这种不含数字的措辞不算合格信号，
    因为"看起来全绿"和"实际跑了几个通过"是两件事。
    """
    global _PASS_COUNT_RE
    if _PASS_COUNT_RE is None:
        _PASS_COUNT_RE = re.compile(
            r"(?<![\w-])(\d+)\s*(?:条|个)?\s*(?:通过|passed\b|pass\b)|\bPASS\s*[=:]\s*(\d+)",
            re.I)
    hits = []
    for m in _PASS_COUNT_RE.finditer(text or ""):
        hits.append(int(m.group(1) or m.group(2)))
    return max(hits) if hits else None


def _has_hard_error(text):
    """硬错误：脚本真的崩了（Traceback / 非零退出说明），不是通过数。"""
    if not text:
        return False
    if "Traceback (most recent call last)" in text:
        return True
    if re.search(r"^\s*(?:bash: .*)?(?:ERROR|Error|FAILED|FAIL): ", text, re.M):
        return True
    if re.search(r"exit(?:ed)? (?:code|status)\s*[:=]?\s*[1-9]", text, re.I):
        return True
    return False


def _fail_signals(text):
    """补认零散失败信号（统一计数器之外的常见写法），返回命中列表。

    关键：`N 通过 / M 失败` 里的计数由 `_fail_count` 负责，这里只找**非计数**写法。
    """
    body = _FAIL_ZERO_RE.sub(" ", text or "")   # 先把显式 0 失败抹掉，再找信号
    hits = []
    for pat, label in _FAIL_SIGNAL_PATTERNS:
        if pat.search(body):
            hits.append(label)
    return hits


_FAIL_SIGNAL_PATTERNS = [
    (re.compile(r"\bFAILED\b"), "FAILED"),
    (re.compile(r"\bFAIL(=|[1-9]\d*)\b"), "FAIL"),
    (re.compile(r"\bnot ok\b", re.I), "not ok"),
    (re.compile(r"[✗✘×✖]"), "✗/×"),
    (re.compile(r"(?m)^[\s\-]*XX\b"), "XX"),
    (re.compile(r"(?<!\d)[1-9]\d*\s*(?:条|个)?\s*(?:失败|不通过)"), "失败计数>0"),
    (re.compile(r"(?<!\d)[1-9]\d*\s+(?:failed|failures?)\b", re.I), "N failed"),
]

# 失败信号的反向白名单：`FAIL=0` / `0 FAILED` 这类显式清零不是失败
_FAIL_ZERO_RE = re.compile(r"\bFAIL(?:ED)?\s*[=:]\s*0\b|\b0\s+(?:FAILED|failed|failures?)\b")


def _judge_test_output(text):
    """判定一段测试回传是否给出**合格信号**（确定性，唯一事实源）。

    三层判定，宁严不松：
      1. 缺内容 → 不通过（没跑别说过）；
      2. 硬错误 / 零散失败信号 / 失败计数>0 → 不通过；
      3. 没看到统一收尾 `N 通过 / M 失败`（或全绿 PASS/OK 收尾）→ **无合格信号，判不通过**。

    第 3 条是 v0.1.1 的关键修补：以前"有输出且没写失败"就算过，
    结果纯 `FAILED` 文本、`ok all pass` 这类没有计数器的回传全被判绿。
    现在缺计数器不再默认绿，而是要求回传方补统一收尾（不能证明通过 = 不算通过）。
    """
    text = text or ""
    if not text.strip():
        return {"ok": False, "why": "缺 test_output（没跑别说过）"}

    fcount = _fail_count(text)
    if fcount:
        return {"ok": False, "why": f"test_output 报告 {fcount} 条失败，别当通过"}
    if _has_hard_error(text):
        return {"ok": False, "why": "test_output 含未处理错误（Traceback/Error/非零退出）"}
    signals = _fail_signals(text)
    if signals:
        return {"ok": False, "why": "test_output 含失败信号：" + "、".join(signals)}

    pcount = _pass_count(text)
    if pcount is None:
        return {"ok": False,
                "why": "无合格信号：未见统一收尾 `N 通过 / M 失败`（缺计数不算通过）"}
    if pcount <= 0:
        return {"ok": False, "why": "通过计数为 0（一条都没跑过通过，不算通过）"}
    return {"ok": True, "why": f"统一收尾 {pcount} 通过 / 0 失败，无失败信号"}


def _keywords(text):
    """从验收条目里抽出可用于 evidence 文本匹配的关键片段（中文按 2 字切）。"""
    import re
    segs = re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z_][\w.-]{2,}", str(text))
    return segs[:6]


def collect(card, result, run_at="local", reopen=False):
    """收本地回传结果 → 核对 → 出结论（不通过就明说，不当成功）。

    **已交付守卫**：卡已 `delivered` 时，默认**拒绝**用一次更差的回传把它冲回 stuck
    （好结果不该被后一次的烂结果覆盖）；确需重跑重判时显式 `reopen=True`，原回执
    压进 `receipt_history` 留痕，不静默覆盖。
    """
    card_id = card["card_id"] if isinstance(card, dict) else card
    cards = _load()
    c = cards.get(card_id)
    if not c:
        return {"ok": False, "error": f"承接卡不存在: {card_id}"}
    if c.get("status") == STATUS_DELIVERED and not reopen:
        return {"ok": False, "error": "该卡已交付（delivered），拒绝用新回传覆盖",
                "hint": "确需重跑重判请显式 reopen=True，原回执会进 receipt_history",
                "status": STATUS_DELIVERED}

    ok, report = verify(c, result)
    receipt = {
        "received_at": _now(),
        "run_at": run_at,
        "passed": ok,
        "report": report,
        "raw": {"changed_files": result.get("changed_files") or [],
                "test_output_len": len(str(result.get("test_output") or "")),
                "evidence_keys": list((result.get("evidence") or {}).keys())},
    }
    if c.get("receipt"):
        c.setdefault("receipt_history", []).append(c["receipt"])
    c["receipt"] = receipt
    c["status"] = STATUS_DELIVERED if ok else STATUS_STUCK
    c["updated_at"] = _now()
    cards[card_id] = c
    _save(cards)
    return {"ok": True, "card_id": card_id, "status": c["status"],
            "passed": ok, "report": report,
            "disposition": "proceed" if ok else "fix_bug"}


# ---------------------------------------------------------------------------
# 五、人可读承接卡（Markdown，供回评）
# ---------------------------------------------------------------------------
def render_md(card):
    d = card["decision"]
    mode_cn = {"full": "全套承接", "partial": "半承接（只出方案+验收标准，执行归本地）",
               "reject": "接不了（已给替代动作）"}.get(d["mode"], d["mode"])
    lines = [
        f"### 承接卡 `{card['card_id']}`",
        "",
        f"- **接的活**：{card['title']}",
        f"- **来源**：{card['origin']}",
        f"- **任务类型 / 谁跑**：{card['kind']} / {RUNTIMES.get(card['runtime'], {}).get('label', card['runtime'])}",
        f"- **承接方式**：{mode_cn}",
        f"- **交付形态**：{d['deliverable'] or '—'}",
        f"- **状态**：{card['status']}",
        f"- **云端是否跑过**：{'是' if card.get('ran_remotely') else '否（运行时在本地）'}",
        "",
    ]
    if card.get("scope_done"):
        lines.append("**做（边界内）**")
        lines += [f"- {s}" for s in card["scope_done"]]
        lines.append("")
    if card.get("scope_not"):
        lines.append("**不做（边界外）**")
        lines += [f"- {s}" for s in card["scope_not"]]
        lines.append("")
    lines.append("**验什么才算完（验收标准）**")
    lines += [f"{i}. {a}" for i, a in enumerate(card["acceptance"], 1)]
    lines.append("")
    if d.get("reasons"):
        lines.append("**判定依据**：" + "；".join(d["reasons"]))
    if d.get("alternative"):
        lines.append(f"**替代动作**：{d['alternative']}")
    h = card.get("handoff")
    if h:
        lines += ["", "**交接单（交本地 runtime 执行，云端不代跑）**"]
        lines += [f"{s['n']}. {s['do']}" for s in h["steps"]]
    r = card.get("receipt")
    if r:
        lines += ["", f"**本地回传核对**：{'通过' if r['passed'] else '不通过'}"]
        lines += [f"- {x['criterion']} → {'✅' if x['ok'] else '❌'} {x['why']}" for x in r["report"]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 六、批扫三态（给人类俯瞰，不混成一个总数）
# ---------------------------------------------------------------------------
def tally():
    cards = ledger()
    delivered = sum(1 for c in cards.values() if c["status"] == STATUS_DELIVERED)
    stuck = sum(1 for c in cards.values() if c["status"] == STATUS_STUCK)
    rejected = sum(1 for c in cards.values() if c["status"] == STATUS_REJECTED)
    open_ = sum(1 for c in cards.values() if c["status"] == STATUS_OPEN)
    total = len(cards)
    return {
        "total": total,
        "delivered": delivered,
        "awaiting_local_run": open_,
        "stuck": stuck,
        "rejected": rejected,
        "delivered_rate": round(delivered / total, 2) if total else 0.0,
        "note": "delivered=本地回传且验收通过；stuck=接了没交；rejected=拒接（带替代动作）",
    }


def capability():
    return {
        "name": "云端承接侧能力 (inbound-take)",
        "version": VERSION,
        "module": MODULE,
        "type": "能力·承接契约",
        "desc": "运行时在本地，云端只承接：承接卡（承了哪件活+验收标准）+ 承接判定（接/半接/拒接带替代）+ 交接单（交本地跑，ran_remotely=False）+ 回传核对 + 三态批扫",
        "interfaces": ["judge", "make_card", "handoff", "collect", "verify",
                       "render_md", "tally", "ledger", "capability"],
        "boundary": "不建云端运行时、不代跑测试、不把已发卡当已交付",
        "run_remotely": False,
    }
