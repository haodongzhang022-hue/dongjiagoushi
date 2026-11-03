# -*- coding: utf-8 -*-
"""
外部验证门禁（expertise.external_validation）
=============================================
为什么单独成模块：「外部验证」是七维里**最容易变成口号**的一维 —— 人人都能写
「已测试通过」，但真正决定可信度的是**功能性代码验证是否真实执行过**。

本模块把「验证」从声明变成**可核验证据**：

  1. **真实执行**（`run_check`）：调用方给出命令 + 期望判据，模块**真的跑**子进程，
     记录退出码/耗时/输出摘要/宿主机，形成不可空的证据对象；
  2. **证据核验**（`verify_claim`）：对一份「声称已验证」的声明做**反造假**检查 ——
     没跑过、跑了失败、只跑了纯静态检查、输出为空、日期异常，全部判不可信；
  3. **功能性判据**（`is_functional`）：只有**行为级**验证（真实调用产生真实产物/
     真实 IO/真实响应）才算功能验证；`grep`/`存在性断言` 这类**静态**检查**不算**。

设计纪律（对齐 AGENTS.md「判不出来 ≠ 通过」）：
  - 任何字段缺失/读不到/超时 → 判 `unknown` 或 `unverified`，**绝不当通过**；
  - 子进程必须带超时，超时即失败（不允许挂死 CI）；
  - 输出只保留摘要（默认 400 字符/次），避免大日志污染上下文。
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from .spec import JUDGE_THRESHOLDS

# 视为「静态检查」的命令特征 —— 它们证明代码长得对，**不证明功能能跑**
STATIC_CHECK_PATTERNS = (
    r"\bgrep\b", r"\brg\b", r"\bfind\b", r"\bls\b", r"\bcat\b", r"\bhead\b",
    r"\btest\s+-[efds]\b", r"\bwc\s+-l\b", r"\bdiff\b", r"\bjq\s+empty\b",
)

# 视为「行为级/功能性」的可执行载体特征
FUNCTIONAL_PATTERNS = (
    r"\bpytest\b", r"\bpython3?\s+-m\s+pytest\b", r"\bpython3?\s+", r"\bnode\b",
    r"\bbash\b", r"\bsh\b", r"\bnpm\s+run\b", r"\bpnpm\b", r"\byarn\b",
    r"\bgo\s+test\b", r"\bcargo\s+test\b", r"\bdotnet\s+test\b", r"\bmake\s+test\b",
    r"\bcurl\b", r"\bcnb\b",
)


def _now():
    return datetime.now(timezone.utc)


def _sha(text, n=12):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:n]


def _summarize(text, limit=400):
    """输出摘要：单次验证只保留尾部 limit 字符（尾部最能反映失败原因）。"""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


def classify_command(command):
    """判定命令属于 static（静态）还是 functional（功能性）。

    返回 dict：{"kind": "functional"|"static"|"unknown", "reason": str}
    """
    if not command or not str(command).strip():
        return {"kind": "unknown", "reason": "命令为空"}
    cmd = str(command)
    if any(re.search(p, cmd) for p in STATIC_CHECK_PATTERNS):
        # 静态模式优先：grep 里带了 python3 也算静态
        if not any(re.search(p, cmd) for p in FUNCTIONAL_PATTERNS):
            return {"kind": "static", "reason": "纯静态检查（grep/test -f 等），不证明功能可跑"}
        # 混合命令（如 sh -c "grep x && python y"）需人工与用例双重确认 → 判 unknown
        return {"kind": "unknown", "reason": "静态与功能性命令混合，须拆分为独立功能性验证"}
    if any(re.search(p, cmd) for p in FUNCTIONAL_PATTERNS):
        return {"kind": "functional", "reason": "含可执行行为载体"}
    return {"kind": "unknown", "reason": "无法判定命令类型，须显式标注"}


def is_functional(command):
    """便捷判据：命令是否构成**功能性代码验证**。"""
    return classify_command(command)["kind"] == "functional"


# ---------------------------------------------------------------------------
# 一、真实执行（不做声明，做证据）
# ---------------------------------------------------------------------------
def run_check(command, cwd=None, timeout=120, expectation="exit0"):
    """**真实执行**一条验证命令，返回可留痕的证据对象。

    expectation:
      - "exit0"（默认）：退出码为 0 即通过；
      - 以 "contains:" 开头：stdout/stderr 需包含指定文本才算通过；
      - "skip-ok"：允许命令不存在（exit 127）视为 skipped（不算通过，也不算失败）。

    返回（任何异常都转成 status，不抛穿业务）：
      {status: pass|fail|skipped|timeout|error, command, kind, cwd, exit_code,
       duration_ms, host, executed_at, output_digest, output_summary, reason}
    """
    started = time.time()
    executed_at = _now().isoformat()
    host = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "local"
    cls = classify_command(command)
    evidence = {
        "command": command,
        "kind": cls["kind"],
        "kind_reason": cls["reason"],
        "cwd": cwd or os.getcwd(),
        "host": host,
        "executed_at": executed_at,
        "exit_code": None,
        "duration_ms": None,
        "output_digest": None,
        "output_summary": "",
        "status": "error",
        "reason": "",
    }
    if not command or not str(command).strip():
        evidence["reason"] = "命令为空，无法执行"
        return evidence

    try:
        # 统一用系统 shell 执行（与 CI 一致）。Windows 上**必须以字符串 + shell=True**
        # 传入：cmd.exe 对双引号有自己的转义规则，若用 argv 列表传 `["cmd.exe","/c",cmd]`
        # 内层引号会被吃掉（实测 `python -c "..."` 变成 `-c "import` → SyntaxError），
        # 造成"验证命令明明能跑却被判失败"的假阴性。
        if sys.platform == "win32":
            proc = subprocess.run(
                command,
                cwd=cwd or None,
                capture_output=True,
                text=True,
                timeout=timeout,
                errors="replace",
                shell=True,
            )
        else:
            shell = os.environ.get("SHELL") or "/bin/sh"
            proc = subprocess.run(
                [shell, "-c", command],
                cwd=cwd or None,
                capture_output=True,
                text=True,
                timeout=timeout,
                errors="replace",
            )
        out = (proc.stdout or "") + (proc.stderr or "")
        evidence["exit_code"] = proc.returncode
        evidence["duration_ms"] = int((time.time() - started) * 1000)
        evidence["output_digest"] = _sha(out)
        evidence["output_summary"] = _summarize(out)
        ev = str(expectation or "exit0")
        if ev == "skip-ok" and proc.returncode == 127:
            evidence["status"] = "skipped"
            evidence["reason"] = "命令不存在（环境未安装），按 skip-ok 记为 skipped（不算通过）"
        elif ev.startswith("contains:"):
            needle = ev[len("contains:"):]
            if proc.returncode == 0 and needle in out:
                evidence["status"] = "pass"
                evidence["reason"] = f"退出码 0 且输出包含 {needle!r}"
            else:
                evidence["status"] = "fail"
                evidence["reason"] = f"未满足 contains:{needle}（exit={proc.returncode}）"
        else:
            if proc.returncode == 0:
                evidence["status"] = "pass"
                evidence["reason"] = "退出码 0"
            else:
                evidence["status"] = "fail"
                evidence["reason"] = f"退出码 {proc.returncode}"
        return evidence
    except subprocess.TimeoutExpired:
        evidence["status"] = "timeout"
        evidence["duration_ms"] = int((time.time() - started) * 1000)
        evidence["reason"] = f"执行超时（>{timeout}s），按失败处置，不允许挂死 CI"
        return evidence
    except Exception as exc:  # noqa: BLE001
        evidence["status"] = "error"
        evidence["duration_ms"] = int((time.time() - started) * 1000)
        evidence["reason"] = f"{type(exc).__name__}: {exc}"
        return evidence


# ---------------------------------------------------------------------------
# 二、证据核验（反造假：声称已验证 ≠ 已验证）
# ---------------------------------------------------------------------------
def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except Exception:  # noqa: BLE001
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def verify_claim(claim, now=None, max_age_days=30):
    """核验一份「验证证据」是否可信。

    claim 期望形态（run_check 的输出本身即可直接喂入）：
      {command, status, executed_at, exit_code, output_digest, output_summary, ...}

    返回：
      {verified: bool, status: verified|unverified|unknown,
       functional: bool, problems: [...], evidence_strength: 0~1}
    """
    now = now or _now()
    problems = []
    if not isinstance(claim, dict):
        return {
            "verified": False,
            "status": "unknown",
            "functional": False,
            "problems": ["证据不是对象，无法核验"],
            "evidence_strength": 0.0,
        }

    command = claim.get("command") or ""
    status = (claim.get("status") or "").lower()
    digest = claim.get("output_digest") or ""
    executed_at = _parse_dt(claim.get("executed_at"))
    cls = classify_command(command)

    # 1) 必须真的执行过
    if not command.strip():
        problems.append("没有验证命令：只声明没执行")
    if not executed_at:
        problems.append("缺少 executed_at：无法证明执行时间")
    if claim.get("exit_code") is None:
        problems.append("缺少 exit_code：无法证明真实跑过")
    if not digest and not (claim.get("output_summary") or "").strip():
        problems.append("没有输出指纹/摘要：无法证明命令产生过真实输出")

    # 2) 必须通过
    if status != "pass":
        problems.append(f"验证状态为 {status or '缺失'}，不是 pass")

    # 3) 必须是功能性（静态检查不算功能验证）
    functional = cls["kind"] == "functional"
    if not functional:
        problems.append(f"非功能性验证（{cls['kind']}）：{cls['reason']}")

    # 4) 证据必须新鲜（陈旧验证不能复用）
    if executed_at:
        age = now - executed_at
        if age < -timedelta(minutes=5):
            problems.append("executed_at 在未来：时间戳不可信")
        elif age > timedelta(days=max_age_days):
            problems.append(f"证据已过期 {age.days} 天（上限 {max_age_days} 天）")

    verified = len(problems) == 0
    strength = 0.0
    if functional and status == "pass" and executed_at and (digest or claim.get("output_summary")):
        strength = 1.0
        if problems:
            strength = 0.5
    elif status == "pass" and executed_at:
        strength = 0.4
    return {
        "verified": verified,
        "status": "verified" if verified else "unverified",
        "functional": functional,
        "problems": problems,
        "evidence_strength": strength,
        "command_kind": cls["kind"],
    }


def gate(claims, now=None):
    """**功能性代码验证门禁**：一组验证证据全过才算过。

    返回：
      {passed: bool, verified_count, functional_count, total,
       problems: [...], evidence: 0~1, verdict}
    verdict ∈ {verified, unverified, unknown}
    """
    if not claims:
        return {
            "passed": False,
            "verified_count": 0,
            "functional_count": 0,
            "total": 0,
            "problems": ["没有任何验证证据：外部验证维度按不可信处置"],
            "evidence": 0.0,
            "verdict": "unknown",
        }
    results = [verify_claim(c, now=now) for c in claims]
    problems = []
    for idx, res in enumerate(results):
        for p in res["problems"]:
            problems.append(f"#{idx + 1} {p}")
    verified = sum(1 for r in results if r["verified"])
    functional = sum(1 for r in results if r["functional"])
    require_exec = JUDGE_THRESHOLDS.get("require_executed_verification", True)
    passed = verified > 0 and (not require_exec or functional > 0) and verified == len(results)
    if passed:
        verdict = "verified"
    elif not problems:
        verdict = "unknown"
    else:
        verdict = "unverified"
    return {
        "passed": passed,
        "verified_count": verified,
        "functional_count": functional,
        "total": len(results),
        "problems": problems,
        "evidence": round(verified / len(results), 3) if results else 0.0,
        "verdict": verdict,
    }
