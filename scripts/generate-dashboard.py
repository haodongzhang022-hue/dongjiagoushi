#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate-dashboard.py —— 可视化 / 二级信息看板自动化生成器
模块：dashboard (v0.1.0, type=init)

功能
----
基于仓库内每个 Issue 的「声明头」（module / type / version / target / update / depends_on），
自动汇总并生成：

  1. 模块版本演进看板：每个模块的版本演进线（能力到哪版、当前待办）
  2. 里程碑表：M0~M8 路线图状态
  3. Issue 声明汇总表：全部已声明 Issue 的归属与状态
  4. 阻塞点 / 待办扫描

输出
----
  docs/DASHBOARD.md  （人类俯瞰决策的二级信息视图）

数据来源
--------
通过 `cnb issues` CLI（自动携带平台鉴权）读取当前仓库的 Issue 列表与正文。
声明头字段同时支持中英文键（如 `模块：` / `module:`、`版本：` / `version:`）。
"""
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict, defaultdict

REPO = os.environ.get("CNB_REPO_SLUG", "dongdongxiaozu/dongjiagoushi")
WEB_HOST = os.environ.get("CNB_WEB_HOST", "cnb.cool")
GROUP = os.environ.get("CNB_ROOT_SLUG", "dongdongxiaozu")
REPO_NAME = os.environ.get("CNB_REPO_NAME", "dongjiagoushi")

MILESTONES = [
    ("M0", "调研", "调研结论"),
    ("M1", "顶层架构拓扑", "docs/ARCHITECTURE.md"),
    ("M2", "可行性验证", "参考仓库核验 + 官方文档核验"),
    ("M3", "工程实施方案（第一版骨架）", "目录结构 + 模块文件"),
    ("M4", "分工与协作规则", "AGENTS.md + settings.yml 扩展位"),
    ("M5", "进度对齐（暂停点）", "CP1/CP2/CP3 护栏"),
    ("M6", "索引建立", "docs/ 索引 + 产物索引"),
    ("M7", "真实场景跑通验证", "用 architect skill 跑真实需求"),
    ("M8", "Issue 声明与模块版本管理机制", "声明头 + 类型表 + 版本线"),
]

# 里程碑与 Issue 的映射（用于标注当前落地位置）
MILESTONE_KEYWORDS = {
    "M0": ["调研"],
    "M1": ["顶层架构", "架构拓扑", "ARCHITECTURE"],
    "M2": ["可行性"],
    "M3": ["工程实施", "第一版骨架", "目录结构"],
    "M4": ["分工", "协作规则", "AGENTS", "settings.yml"],
    "M5": ["进度对齐", "暂停点", "CP1", "CP2", "CP3"],
    "M6": ["索引"],
    "M7": ["真实场景", "跑通验证"],
    "M8": ["声明", "版本管理", "ISSUE_MANAGEMENT"],
}

TYPE_INFO = {
    "init": ("建模块根节点", "v0.1.0"),
    "update": ("MINOR 增强", "升 MINOR"),
    "fix": ("PATCH 修复", "升 PATCH"),
    "standalone": ("一次性任务", "不占版本"),
}
TYPE_ICON = {"init": "🆕", "update": "🔺", "fix": "🛠️", "standalone": "📄"}


def run_cmd(args):
    """执行命令并返回 (returncode, stdout)"""
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout


def fetch_issues():
    """通过 cnb CLI 拉取全部 Issue（含正文）"""
    issues = []
    page = 1
    while True:
        rc, out = run_cmd([
            "cnb", "issues", "list-issues",
            "--repo", REPO, "--page", str(page), "--page-size", "100", "--verbose",
        ])
        if rc != 0:
            sys.stderr.write(f"[warn] list-issues 失败: {out}\n")
            break
        try:
            payload = json.loads(out)
            data = payload.get("data", [])
        except Exception as e:
            sys.stderr.write(f"[warn] 解析列表失败: {e}\n")
            break
        if not data:
            break
        for item in data:
            number = item.get("number")
            rc2, out2 = run_cmd([
                "cnb", "issues", "get-issue",
                "--repo", REPO, "--number", str(number), "--verbose",
            ])
            body = ""
            if rc2 == 0:
                try:
                    body = json.loads(out2).get("data", {}).get("body", "") or ""
                except Exception:
                    body = ""
            issues.append({
                "number": str(number),
                "title": item.get("title", "").strip(),
                "state": item.get("state", ""),
                "created_at": item.get("created_at", ""),
                "body": body,
            })
        # 判断是否还有下一页
        total = payload.get("total", 0)
        if page * 100 >= total:
            break
        page += 1
    return issues


def parse_decl(body):
    """解析 Issue 正文中的声明头字段（支持中英文键）"""
    decl = OrderedDict()
    # 字段别名：优先中英均支持
    aliases = {
        "module": ["module", "模块"],
        "type": ["type", "类型"],
        "target": ["target", "目标"],
        "version": ["version", "版本"],
        "update": ["update", "更新"],
        "depends_on": ["depends_on", "依赖"],
    }
    pattern = re.compile(r"^\s*(module|模块|type|类型|target|目标|version|版本|update|更新|depends_on|依赖)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)
    for line in body.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        key = m.group(1).lower()
        value = m.group(2).strip()
        for field, keys in aliases.items():
            if key in keys:
                decl[field] = value
                break
    return decl


def normalize_type(raw):
    """把 type 字段规整为 init/update/fix/standalone"""
    raw = (raw or "").lower().strip()
    # 处理 "init（新模块）" 这类带说明的形式
    raw = re.split(r"[（(]", raw)[0].strip()
    if raw in TYPE_INFO:
        return raw
    if raw in ("建立", "新建", "首版"):
        return "init"
    if raw in ("增强", "迭代", "加强"):
        return "update"
    if raw in ("修复", "修", "小改"):
        return "fix"
    return "standalone"


def sort_key(decl):
    """版本排序键：无版本号放最后"""
    v = decl.get("version", "")
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", v)
    if m:
        return (0, int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (1, 0, 0, 0)


def build_module_lines(issues, decls):
    """按模块聚合版本演进线"""
    by_module = defaultdict(list)
    for issue, decl in zip(issues, decls):
        if not decl:
            continue
        module = decl.get("module", "").strip()
        if not module:
            continue
        by_module[module].append((issue, decl))
    # 每个模块内按版本排序
    for module in by_module:
        by_module[module].sort(key=lambda x: sort_key(x[1]))
    return OrderedDict(sorted(by_module.items()))


def match_milestone(text):
    """根据 Issue 标题/正文匹配里程碑"""
    if not text:
        return []
    hits = []
    for mid, kw in MILESTONE_KEYWORDS.items():
        if any(k in text for k in kw):
            hits.append(mid)
    return hits


def render():
    issues = fetch_issues()
    decls = [parse_decl(i["body"]) for i in issues]

    lines = []
    lines.append("# 📊 可视化 / 二级信息看板")
    lines.append("")
    lines.append("> 本文件由 `scripts/generate-dashboard.py` **自动生成**，用于人类俯瞰决策。")
    lines.append("> 数据源：仓库各 Issue 声明头（module / type / version / target / update / depends_on）。")
    lines.append("> ⚠️ 请勿手动编辑本文件；刷新方式见文末「刷新指南」。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 1. 模块版本演进看板 =====
    lines.append("## 一、模块版本演进看板")
    lines.append("")
    lines.append("每个模块独立一条语义化版本线；看板显示「能力到哪版、当前待办是什么」。")
    lines.append("")
    by_module = build_module_lines(issues, decls)
    if not by_module:
        lines.append("_暂无已声明 module 的 Issue。_")
    for module, items in by_module.items():
        lines.append(f"### 模块 `{module}`")
        lines.append("")
        lines.append("| Issue | type | 版本 | 目标 / 更新 | 状态 |")
        lines.append("|-------|------|------|-------------|------|")
        for issue, decl in items:
            num = issue["number"]
            t = normalize_type(decl.get("type", "standalone"))
            ver = decl.get("version", "—")
            target = decl.get("target") or decl.get("update") or "—"
            target = (target or "").replace("|", "\\|")
            state = issue.get("state", "")
            state_icon = "🟢" if state == "open" else "⚪"
            link = f"#{num}"
            lines.append(f"| [{link}](https://{WEB_HOST}/{GROUP}/{REPO_NAME}/-/issues/{num}) | {TYPE_ICON.get(t, '')} {t} | {ver} | {target} | {state_icon} {state} |")
        lines.append("")
    if not by_module:
        lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 2. 里程碑表 =====
    lines.append("## 二、里程碑表（M0~M8）")
    lines.append("")
    lines.append("> 里程碑状态需人工在 `docs/ROADMAP.md` 维护；此处根据已声明 Issue 的关键词自动标注落地线索。")
    lines.append("")
    lines.append("| 阶段 | 内容 | 交付物 | 落地线索 |")
    lines.append("|------|------|--------|----------|")
    for mid, content, deliverable in MILESTONES:
        hits = []
        for issue, decl in zip(issues, decls):
            text = issue["title"] + "\n" + issue["body"]
            if mid in match_milestone(text):
                hits.append(f"[#{issue['number']}](https://{WEB_HOST}/{GROUP}/{REPO_NAME}/-/issues/{issue['number']})")
        # ROADMAP 中状态标注
        roadmap_status = "?"
        try:
            with open(os.path.join(os.path.dirname(__file__), "..", "docs", "ROADMAP.md")) as f:
                rmd = f.read()
            for line in rmd.splitlines():
                if line.startswith(f"| {mid} |"):
                    cells = [c.strip() for c in line.strip("|").split("|")]
                    if len(cells) >= 4:
                        roadmap_status = cells[3]
        except Exception:
            roadmap_status = "?"
        hit_str = ", ".join(hits) if hits else "—"
        lines.append(f"| {mid} | {content} | {deliverable} | 状态 `{roadmap_status}` · 线索 {hit_str} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 3. Issue 声明汇总表 =====
    lines.append("## 三、Issue 声明汇总表")
    lines.append("")
    lines.append("| Issue | 模块 | type | 版本 | 目标 | 依赖 | 状态 |")
    lines.append("|-------|------|------|------|------|------|------|")
    declared_any = False
    for issue, decl in zip(issues, decls):
        num = issue["number"]
        if decl:
            declared_any = True
            module = decl.get("module", "—")
            t = normalize_type(decl.get("type", "standalone"))
            ver = decl.get("version", "—")
            target = (decl.get("target") or "—").replace("|", "\\|")
            dep = decl.get("depends_on", "—")
        else:
            module = "—"
            t = "—"
            ver = "—"
            target = "（未声明）"
            dep = "—"
        state = issue.get("state", "")
        state_icon = "🟢" if state == "open" else "⚪"
        link = f"https://{WEB_HOST}/{GROUP}/{REPO_NAME}/-/issues/{num}"
        lines.append(f"| [#{num}]({link}) | `{module}` | {t} | {ver} | {target} | {dep} | {state_icon} {state} |")
    if not declared_any:
        pass
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 4. 待办 / 阻塞点扫描 =====
    lines.append("## 四、待办 / 阻塞点扫描")
    lines.append("")
    open_issues = [i for i in issues if i.get("state") == "open"]
    lines.append(f"当前 open Issue：**{len(open_issues)}** / 总 {len(issues)}。")
    lines.append("")
    lines.append("| Issue | 标题 | 模块 | 阻塞线索 |")
    lines.append("|-------|------|------|----------|")
    for issue in open_issues:
        decl = parse_decl(issue["body"])
        module = decl.get("module", "—")
        blocker = "⏸ 暂停点" if re.search(r"CP1|CP2|CP3|暂停|阻塞|blocked", issue["title"] + issue["body"]) else "—"
        link = f"https://{WEB_HOST}/{GROUP}/{REPO_NAME}/-/issues/{issue['number']}"
        title = issue["title"].replace("|", "\\|")
        lines.append(f"| [#{issue['number']}]({link}) | {title} | `{module}` | {blocker} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 5. 刷新指南 =====
    lines.append("## 五、刷新指南")
    lines.append("")
    lines.append("```bash")
    lines.append("python3 scripts/generate-dashboard.py   # 重新生成 docs/DASHBOARD.md")
    lines.append("```")
    lines.append("")
    lines.append("可在 `.cnb.yml` 流水线中挂一个 job，在 `issue.comment@npc` / `issue` 事件后自动刷新本看板。")
    lines.append("")

    return "\n".join(lines), issues, by_module


def main():
    output_path = os.path.join(os.path.dirname(__file__), "..", "docs", "DASHBOARD.md")
    content, issues, by_module = render()
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[ok] 已生成 {output_path}")
    print(f"[info] 读取 Issue {len(issues)} 个，识别到模块 {len(by_module)} 个")


if __name__ == "__main__":
    main()
