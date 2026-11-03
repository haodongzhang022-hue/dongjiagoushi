#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Issue 唯一标题契约 · 派发与治理脚本（issue-contract）
=====================================================
把 `local-agent/expertise/issue_contract.py` 的判定接到真实云端操作上。

三种模式（**默认 dry-run，绝不误写**）：

  --mode audit      清点现有 Issue，输出：低信号清单 / 重复分组 / 近重复 / 契约覆盖率
  --mode plan       用契约派发一批「下一步工作」Issue（幂等：已存在则复用）
  --mode dedupe     生成收并计划（保留主号 + 关闭重复号 + 闭环注释文本）

安全边界：
  1. 默认 `--dry-run`；写云端必须显式加 `--apply`（不可逆动作不自动执行）；
  2. 关闭 Issue 一律带**收并注释回指主号**，不静默消失；
  3. 低信号 Issue **不删除**，只建议打标签 + 关闭（保留审计痕迹）；
  4. 依赖 `cnb` CLI；未安装时明确报错退出，不吞异常。

用法：
    python3 scripts/issue-contract.py --mode audit --repo dongdongxiaozu/dongjiagoushi
    python3 scripts/issue-contract.py --mode dedupe --repo ... --dry-run
    python3 scripts/issue-contract.py --mode dedupe --repo ... --apply --yes
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_LOCAL_AGENT = os.path.join(os.path.dirname(_HERE), "local-agent")
if _LOCAL_AGENT not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT)

from expertise import issue_contract as ic  # noqa: E402


def _cnb_argv(args):
    """构造调用 cnb CLI 的 argv（跨平台）。

    平台差异：Windows 上 `cnb` 往往是 `cnb.ps1`/`cnb.cmd` 包装脚本，**不能直接
    当可执行文件启动**（CreateProcess 找不到）——实测会报 FileNotFoundError。
    因此：
      - 找到 cnb 的**真实 JS 入口**（npm 全局 bin 下的 cnb 脚本）→ 用当前解释器/`node` 启动；
      - 否则在 Windows 上走 `cmd /c cnb ...` / `powershell -File cnb.ps1 ...`；
      - 类 Unix 直接执行 `cnb`。
    """
    exe = shutil.which("cnb")
    if exe:
        lower = exe.lower()
        if lower.endswith((".exe", "")) and not lower.endswith((".ps1", ".cmd", ".bat")):
            return [exe] + args
        if lower.endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", exe] + args
        if lower.endswith(".ps1"):
            return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", exe] + args
    if sys.platform == "win32":
        return ["cmd.exe", "/c", "cnb"] + args
    return ["cnb"] + args


def _run(argv, timeout=180):
    """调用 cnb CLI；返回 (rc, stdout, stderr)。不经 shell（防注入）。"""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              errors="replace")
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", ("cnb CLI 不可用：未找到 cnb 可执行入口。"
                         "请确认 `cnb --version` 在本机可用，或设置 PATH。")
    except subprocess.TimeoutExpired:
        return 124, "", f"命令超时（>{timeout}s）：{' '.join(argv[:4])}"


def fetch_issues(repo, state="all", page_size=100, max_pages=10):
    """拉取 Issue 清单（含已关闭，用于收并判定）。返回 [{number,title,state,comment_count}]。"""
    out = []
    for page in range(1, max_pages + 1):
        argv = _cnb_argv(["issues", "list-issues", "--repo", repo, "--page", str(page),
                          "--page-size", str(page_size)])
        if state != "all":
            argv += ["--state", state]
        rc, stdout, stderr = _run(argv)
        if rc != 0:
            raise RuntimeError(f"拉取 Issue 失败（page {page}）：{stderr.strip()[:300]}")
        # cnb CLI 输出是 yaml 风格文本；用宽松解析提取 number/title/state/comment_count
        out.extend(_parse_issue_list(stdout))
        if "totalPages" in stdout:
            try:
                total_pages = int(stdout.split("totalPages:", 1)[1].splitlines()[0].strip())
                if page >= total_pages:
                    break
            except (ValueError, IndexError):
                break
        elif len(out) < page * page_size:
            break
    return out


def _parse_issue_list(text):
    """从 cnb CLI 的 yaml 风格输出里提取需要的字段（容错：缺字段不崩）。"""
    items, cur = [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("- number:"):
            if cur:
                items.append(cur)
            cur = {"number": stripped.split(":", 1)[1].strip().strip('"')}
            continue
        if cur is None:
            continue
        for key in ("title", "state", "comment_count"):
            if stripped.startswith(key + ":"):
                val = stripped.split(":", 1)[1].strip().strip('"')
                cur[key] = val
                break
    if cur:
        items.append(cur)
    for item in items:
        try:
            item["comment_count"] = int(item.get("comment_count") or 0)
        except (TypeError, ValueError):
            item["comment_count"] = 0
    return items


def audit(issues):
    """清点：低信号 / 重复 / 近重复 / 契约覆盖率。"""
    low = []
    contract_ok = 0
    keyed = {}
    for issue in issues:
        title = issue.get("title", "")
        is_low, why = ic.is_low_signal(title)
        key = ic.issue_key(title)
        if key:
            contract_ok += 1
        elif is_low:
            low.append({"number": issue.get("number"), "title": title, "reason": why})
        if key:
            keyed.setdefault(key, []).append(issue.get("number"))
    dup_titles = {}
    for issue in issues:
        dup_titles.setdefault(ic.normalize(issue.get("title", "")), []).append(issue.get("number"))
    title_dups = {t: nums for t, nums in dup_titles.items() if len(nums) > 1}
    key_dups = {k: nums for k, nums in keyed.items() if len(nums) > 1}
    near = ic.plan([], issues).get("near_duplicates", [])
    total = len(issues) or 1
    return {
        "total": len(issues),
        "contract_ratio": round(contract_ok / total, 3),
        "low_signal": low,
        "low_signal_count": len(low),
        "title_duplicates": title_dups,
        "key_duplicates": key_dups,
        "near_duplicates": near[:50],
        "near_duplicate_count": len(near),
    }


def print_audit(rep):
    print("=" * 68)
    print(f"Issue 契约清点：共 {rep['total']} 条 ｜ 契约覆盖率 {rep['contract_ratio']:.1%}")
    print(f"  低信号（测试流/占位）：{rep['low_signal_count']}")
    print(f"  同名重复组：{len(rep['title_duplicates'])} 组 ｜ 同 key 重复：{len(rep['key_duplicates'])} 组")
    print(f"  近重复（相似度>=0.9）：{rep['near_duplicate_count']}")
    print("=" * 68)
    if rep["title_duplicates"]:
        print("\n【同名重复】")
        for title, nums in rep["title_duplicates"].items():
            print(f"  ×{len(nums):<2} {title[:40]!r}  ->  {', '.join('#' + n for n in nums)}")
    if rep["low_signal"]:
        print("\n【低信号 Issue（建议：打标签 + 关闭，不删除）】")
        for item in rep["low_signal"][:60]:
            print(f"  #{item['number']:<5} {item['title'][:36]}")
        if len(rep["low_signal"]) > 60:
            print(f"  … 其余 {len(rep['low_signal']) - 60} 条省略")


def print_dedupe(plan):
    print("=" * 68)
    print(f"收并计划：{len(plan['groups'])} 组待收并 ｜ 近重复 {len(plan['near_duplicates'])} 对（需人工判断）")
    print("=" * 68)
    for group in plan["groups"]:
        print(f"\n[{group['title'][:44]}]")
        print(f"  保留主号：#{group['keep']}")
        print(f"  关闭：{', '.join('#' + n for n in group['close'])}")
    if plan["near_duplicates"]:
        print("\n【近重复（语义重合，交人工判断）】")
        for pair in plan["near_duplicates"][:20]:
            print(f"  #{pair['a']} ~ #{pair['b']}  sim={pair['similarity']}  {pair['titles'][0][:28]!r}")


def apply_dedupe(repo, plan, yes=False):
    """执行收并：先给重复号打收并注释，再关闭。必须 --yes 才真正执行。"""
    if not yes:
        print("\n⚠️  写操作需要显式 --yes 确认（不可逆）。本次未执行任何写动作。")
        return {"closed": [], "commented": []}
    closed, commented = [], []
    for group in plan["groups"]:
        for num in group["close"]:
            # 1) 先留收并注释（不静默消失）。
            #    注意：`cnb issues comment` 是**快捷命令、不吃 --repo/--number**，
            #    必须用完整工具名 `post-issue-comment`（实测 2026-11-03）。
            rc, out, err = _run(_cnb_argv(["issues", "post-issue-comment", "--repo", repo,
                                           "--number", str(num),
                                           "--body", group["comment"]]))
            if rc == 0:
                commented.append(num)
            else:
                print(f"  ❌ 评论失败 #{num}: {(err or out).strip()[:160]}")
            # 2) 再关闭。`close` 同样是快捷命令；用 `update-issue` 显式置状态。
            rc, out, err = _run(_cnb_argv(["issues", "update-issue", "--repo", repo,
                                           "--number", str(num),
                                           "--state", "closed",
                                           "--state-reason", "not_planned"]))
            if rc == 0:
                closed.append(num)
            else:
                print(f"  ❌ 关闭失败 #{num}: {(err or out).strip()[:160]}")
    return {"closed": closed, "commented": commented}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Issue 唯一标题契约 · 派发与治理")
    parser.add_argument("--mode", choices=["audit", "dedupe", "plan"], default="audit")
    parser.add_argument("--repo", default="dongdongxiaozu/dongjiagoushi")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", help="真正写云端（不可逆，需配合 --yes）")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args(argv)

    try:
        issues = fetch_issues(args.repo)
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    if not issues:
        print("⚠️ 未取到任何 Issue（检查 repo 名与 cnb 鉴权）", file=sys.stderr)
        return 2

    if args.mode == "audit":
        rep = audit(issues)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            print_audit(rep)
        return 0

    if args.mode == "dedupe":
        plan = ic.dedupe_plan(issues)
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print_dedupe(plan)
        if args.apply:
            result = apply_dedupe(args.repo, plan, yes=args.yes)
            print(f"\n执行结果：关闭 {len(result['closed'])} 条，评论 {len(result['commented'])} 条")
        else:
            print("\n（dry-run：未写云端。确认计划后加 --apply --yes 执行）")
        return 0

    print("plan 模式需要 --issues-file（略）；请用 audit/dedupe。", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
