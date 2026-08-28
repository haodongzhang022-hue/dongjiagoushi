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
    # 字段别名：优先中英均支持（含双版本 module_version / agent_version）
    aliases = {
        "module": ["module", "模块"],
        "module_version": ["module_version", "模块版本", "mv", "模块版"],
        "agent": ["agent", "角色", "agent_role"],
        "agent_version": ["agent_version", "agent 版本", "角色版本", "av"],
        "type": ["type", "类型"],
        "target": ["target", "目标"],
        "version": ["version", "版本"],
        "update": ["update", "更新"],
        "depends_on": ["depends_on", "依赖"],
    }
    pattern = re.compile(
        r"^\s*(module_version|module|模块版本|模块版|mv|agent_version|agent 版本|角色版本|av|agent_role|agent|角色|type|类型|target|目标|version|版本|update|更新|depends_on|依赖)\s*[:：]\s*(.+?)\s*$",
        re.IGNORECASE,
    )
    for line in body.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        key = m.group(1).lower().strip()
        value = m.group(2).strip()
        # 匹配字段：复合键优先（module_version 优先于 module，agent_version 优先于 agent/version）
        field = None
        for fld, keys in aliases.items():
            if key in keys:
                field = fld
                # module_version/agent_version 这类复合键优先；命中后继续尝试更优匹配
                if key.startswith("module_version") or key.startswith("agent_version"):
                    field = "module_version" if key.startswith("module_version") else "agent_version"
                break
        if field is None:
            continue
        # 去掉括号说明（如 "v0.2.0（增强）" → "v0.2.0"）
        decl[field] = re.split(r"[（(]", value)[0].strip()
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
    """版本排序键：按 module_version 排（无则退回 version，再退 agent_version）；无版本号放最后"""
    v = decl.get("module_version") or decl.get("version") or decl.get("agent_version") or ""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", v)
    if m:
        return (0, int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (1, 0, 0, 0)


def build_module_lines(issues, decls):
    """按模块聚合版本演进线（module_version 维度）"""
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


def build_agent_lines(issues, decls):
    """按 agent 角色聚合版本演进线（agent_version 维度）"""
    by_agent = defaultdict(list)
    for issue, decl in zip(issues, decls):
        if not decl:
            continue
        agent = decl.get("agent", "").strip()
        if not agent:
            continue
        by_agent[agent].append((issue, decl))
    for agent in by_agent:
        by_agent[agent].sort(key=lambda x: sort_key(x[1]))
    return OrderedDict(sorted(by_agent.items()))


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
    lines.append("> 数据源：仓库各 Issue 声明头（module / module_version / agent / agent_version / type / target / update / depends_on）。")
    lines.append("> 版本强制：非整体版本，而是【模块版本 + agent 版本】双维度独立升版、以较小迭代单位推进（详见 docs/ISSUE_MANAGEMENT.md）。")
    lines.append("> ⚠️ 请勿手动编辑本文件；刷新方式见文末「刷新指南」。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 1. 模块版本演进看板 =====
    lines.append("## 一、模块版本演进看板（module_version）")
    lines.append("")
    lines.append("每个模块独立一条语义化版本线；看板显示「能力到哪版、当前待办是什么」。")
    lines.append("")
    by_module = build_module_lines(issues, decls)
    if not by_module:
        lines.append("_暂无已声明 module 的 Issue。_")
    for module, items in by_module.items():
        lines.append(f"### 模块 `{module}`")
        lines.append("")
        lines.append("| Issue | type | 模块版本 | 目标 / 更新 | 状态 |")
        lines.append("|-------|------|---------|-------------|------|")
        for issue, decl in items:
            num = issue["number"]
            t = normalize_type(decl.get("type", "standalone"))
            ver = decl.get("module_version") or decl.get("version") or "—"
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

    # ===== 1b. Agent 角色版本演进看板 =====
    lines.append("## 二、Agent 角色版本演进看板（agent_version）")
    lines.append("")
    lines.append("每个 agent 角色独立一条语义化版本线；看板显示「角色能力到哪版」。一个 Issue 只在一个最小迭代单位（单一模块 / 单一 agent）上升版。")
    lines.append("")
    by_agent = build_agent_lines(issues, decls)
    if not by_agent:
        lines.append("_暂无已声明 agent 的 Issue。_")
    for agent, items in by_agent.items():
        lines.append(f"### Agent `{agent}`")
        lines.append("")
        lines.append("| Issue | type | Agent版本 | 目标 / 更新 | 状态 |")
        lines.append("|-------|------|----------|-------------|------|")
        for issue, decl in items:
            num = issue["number"]
            t = normalize_type(decl.get("type", "standalone"))
            ver = decl.get("agent_version") or "—"
            target = decl.get("target") or decl.get("update") or "—"
            target = (target or "").replace("|", "\\|")
            state = issue.get("state", "")
            state_icon = "🟢" if state == "open" else "⚪"
            link = f"#{num}"
            lines.append(f"| [{link}](https://{WEB_HOST}/{GROUP}/{REPO_NAME}/-/issues/{num}) | {TYPE_ICON.get(t, '')} {t} | {ver} | {target} | {state_icon} {state} |")
        lines.append("")
    if not by_agent:
        lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 1c. 公司化三战线看板（M4 全链贯通 · 二级信息俯瞰） =====
    lines.append("## 三、公司化三战线看板（公司化体系 · Issue #18 · M4 全链贯通）")
    lines.append("")
    lines.append("> 公司化三战线：**市场获客线**（公司能否活着）→ **交付流水线**（接单到交付）→ **能力底座线**（持续开发）。")
    lines.append("> 数据源：`local-agent/team.yaml` 三战线角色 + `src/memory/schema.py` 语义触发原型 + `docs/COMPANY_MODEL.md` 里程碑。")
    lines.append("> 里程碑 M1 市场获客线 ✅ / M2 交付线增强 ✅ / M3 能力底座线 ✅ / **M4 全链贯通**（三战线接力 + 语义触发 + 公司看板）。")
    lines.append("")
    repo_root = os.path.join(os.path.dirname(__file__), "..")

    # 从 team.yaml 读取三战线角色（本地数据，无需网络）
    company_lines = {"市场获客线": [], "交付流水线": [], "能力底座线": []}
    try:
        import yaml
        with open(os.path.join(repo_root, "local-agent", "team.yaml"), encoding="utf-8") as f:
            _team = yaml.safe_load(f)
        _roles = _team.get("roles", [])
        _by_name = {r["name"]: r for r in _roles}
        for _rname in ["架构·找需求", "架构·价值确认", "架构·竞品分析", "市场·销售", "市场·客服"]:
            if _rname in _by_name:
                company_lines["市场获客线"].append(_rname)
        for _rname in ["架构·秘书", "架构·产品", "架构·总师", "架构·经理", "架构·小组长",
                        "架构·开发", "架构·评审", "架构·对齐", "架构·找工具", "架构·测试"]:
            if _rname in _by_name:
                company_lines["交付流水线"].append(_rname)
        for _rname in ["架构·工具开发", "架构·优化", "架构·数据管理", "架构·运维"]:
            if _rname in _by_name:
                company_lines["能力底座线"].append(_rname)
    except Exception as _e:
        company_lines = {"市场获客线": [], "交付流水线": [], "能力底座线": []}

    # 三战线表格（干净输出）
    lines.append("| 战线 | 职责 | 角色清单 | 里程碑 |")
    lines.append("|------|------|----------|--------|")
    for _line, _label, _status in [
        ("市场获客线", "找单/选单/成单/服务（决定做什么单、有没有价值）", "✅ M1"),
        ("交付流水线", "接单→澄清→架构→分工→实现→评审→对齐→测试→交付", "✅ M2"),
        ("能力底座线", "工具沉淀/优化/数据管理/运维（持续开发更快更稳）", "✅ M3"),
    ]:
        _roles_str = ", ".join(f"`{r}`" for r in company_lines[_line]) if company_lines[_line] else "—"
        lines.append(f"| **{_line}** | {_label} | {_roles_str} | {_status} |")

    # 语义触发覆盖（从 schema ROLE_PROTOTYPES 统计）
    lines.append("")
    lines.append("### 三战线角色语义触发覆盖")
    lines.append("")
    try:
        sys.path.insert(0, os.path.join(repo_root, "src"))
        from memory.schema import ROLE_PROTOTYPES
        _proto_keys = set(ROLE_PROTOTYPES.keys())
        _total = 0
        for _k in ["架构·找需求", "架构·价值确认", "架构·竞品分析", "市场·销售", "市场·客服",
                   "架构·工具开发", "架构·优化", "架构·数据管理", "架构·运维",
                   "架构·经理", "架构·秘书", "架构·小组长", "架构·对齐", "架构·找工具",
                   "架构·总师助理", "架构·监控哨兵", "架构·进度推手", "架构·数据管理员"]:
            if _k in _proto_keys:
                _total += 1
        lines.append(f"- **语义触发原型登记**：{_total} 个三战线/新增角色已登记（`ROLE_PROTOTYPES`），语义命中即可触发，无需显式 `[触发]`。")
    except Exception:
        lines.append("- 语义触发原型登记：读取失败。")
    lines.append("")
    lines.append("### 三战线接力拓扑")
    lines.append("")
    lines.append("```")
    lines.append("市场获客线:  找需求 → 价值确认 → 竞品分析 → 销售成单 → 客服")
    lines.append("                    │")
    lines.append("                    ▼ 成单需求")
    lines.append("交付流水线:  秘书 → 产品 → 总师 → 经理 → 小组长 → 开发 → 评审 → 对齐 → 测试 → 交付")
    lines.append("                    │")
    lines.append("                    ▼ 交付产物/沉淀")
    lines.append("能力底座线:  工具开发 → 优化 → 数据管理 → 运维")
    lines.append("```")
    lines.append("")
    lines.append("> **关键洞察**：交付线产出工具/数据/优化经验反馈给底座线，底座线让下次交付更快 → 成本更低 → 市场更有竞争力——这是「持续开发能力 + 市场存活」的来源（详见 docs/COMPANY_MODEL.md）。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 2. 里程碑表 =====
    lines.append("## 四、里程碑表（M0~M8）")
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

    # ===== 3. Issue 声明汇总表（双版本） =====
    lines.append("## 五、Issue 声明汇总表（双版本）")
    lines.append("")
    lines.append("| Issue | 模块 | 模块版本 | agent | agent版本 | type | 目标 | 依赖 | 状态 |")
    lines.append("|-------|------|---------|-------|----------|------|------|------|------|")
    declared_any = False
    for issue, decl in zip(issues, decls):
        num = issue["number"]
        if decl:
            declared_any = True
            module = decl.get("module", "—")
            mv = decl.get("module_version") or decl.get("version") or "—"
            agent = decl.get("agent", "—")
            av = decl.get("agent_version", "—")
            t = normalize_type(decl.get("type", "standalone"))
            target = (decl.get("target") or "—").replace("|", "\\|")
            dep = decl.get("depends_on", "—")
        else:
            module = "—"
            mv = "—"
            agent = "—"
            av = "—"
            t = "—"
            target = "（未声明）"
            dep = "—"
        state = issue.get("state", "")
        state_icon = "🟢" if state == "open" else "⚪"
        link = f"https://{WEB_HOST}/{GROUP}/{REPO_NAME}/-/issues/{num}"
        lines.append(f"| [#{num}]({link}) | `{module}` | {mv} | `{agent}` | {av} | {t} | {target} | {dep} | {state_icon} {state} |")
    if not declared_any:
        pass
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 4. 待办 / 阻塞点扫描 =====
    lines.append("## 六、待办 / 阻塞点扫描")
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

    # ===== 5. 版本合规 / 迭代冲突扫描（版本强制核查） =====
    lines.append("## 七、版本合规 / 迭代冲突扫描（版本强制核查）")
    lines.append("")
    lines.append("核查每张 Issue 是否满足「版本强制 + 双维度独立 + 较小迭代单位」：")
    lines.append("- 未写明 `module_version`（模块维度）的 Issue；")
    lines.append("- 涉及 agent 能力却未写明 `agent_version`（agent 维度）的 Issue；")
    lines.append("- 疑似「跨维度/跨模块强推整体版本」、或依赖了未声明 Issue 的高合并冲突风险项。")
    lines.append("")
    no_mv = []
    no_av = []
    for issue, decl in zip(issues, decls):
        if not decl:
            continue
        num = issue["number"]
        t = normalize_type(decl.get("type", "standalone"))
        if t == "standalone":
            continue
        if not (decl.get("module_version") or decl.get("version")):
            no_mv.append(num)
        if decl.get("agent") and not decl.get("agent_version"):
            no_av.append(num)
    lines.append("| 核查项 | 缺省 Issue | 影响 |")
    lines.append("|--------|-----------|------|")
    lines.append(f"| 模块版本缺失（应写 `module_version`） | {', '.join('#' + n for n in no_mv) if no_mv else '✅ 无'} | 看板无法显示模块版本线，无法版本管理 |")
    lines.append(f"| agent 能力缺失 `agent_version` | {', '.join('#' + n for n in no_av) if no_av else '✅ 无'} | agent 维度版本线缺失，无法追踪角色能力 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 6. 框架健康度（框架自升级维度） =====
    lines.append("## 八、框架健康度（framework 自升级维度）")
    lines.append("")
    lines.append("> 框架整体 = AGENTS.md + .cnb.yml + SKILL.md + settings.yml + docs/ + src/memory/。")
    lines.append("> 本维度把「框架自身」纳入版本演进，展示各模块/角色版本线 + 测试信号灯 + 待办升级项，供人类俯瞰框架健康（详见 docs/FRAMEWORK_UPGRADE.md）。")
    lines.append("")

    # 6a. 模块 / 角色 版本线覆盖统计
    lines.append("### 6.1 模块与角色版本线覆盖")
    lines.append("")
    lines.append("| 维度 | 已覆盖版本线 | 说明 |")
    lines.append("|------|-------------|------|")
    declared_modules = [m for m in by_module.keys()] if by_module else []
    mod_str = ", ".join(f"`{m}`" for m in declared_modules) if declared_modules else "—"
    declared_agents = [a for a in by_agent.keys()] if by_agent else []
    agent_str = ", ".join(f"`{a}`" for a in declared_agents) if declared_agents else "—"
    lines.append(f"| 模块版本线 | {mod_str} | 各模块独立演进（module_version） |")
    lines.append(f"| agent 版本线 | {agent_str} | 各角色独立演进（agent_version） |")
    lines.append(f"| 框架自升级线 | `framework` | 跨模块/方法论/测试红线整体升级（type=upgrade，见 FRAMEWORK_UPGRADE.md） |")
    lines.append("")

    # 6b. 测试信号灯（静态读取测试脚本头声明）
    lines.append("### 6.2 测试信号灯")
    lines.append("")
    lines.append("| 测试脚本 | 覆盖 | 状态(本地需自行运行) |")
    lines.append("|---------|------|--------------------|")
    test_map = [
        ("test_architect_system.sh", "产物完整性/八步/CP护栏/触发强制化/回转打断"),
        ("test_functional_links.sh", "真实功能链路（数据获取/看板/RAG）"),
        ("test_relay_workflow.sh", "接力/回转/打断 可复现"),
        ("test_memory_store.sh", "记忆库+语义向量触发+双后端兼容"),
        ("test_doc_consistency.sh", "文档-实现一致性（防漂移）"),
    ]
    for script, cov in test_map:
        exists = os.path.exists(os.path.join(os.path.dirname(__file__), "..", "tests", script))
        st = "✅ 存在" if exists else "❌ 缺失"
        lines.append(f"| {script} | {cov} | {st} |")
    lines.append("")

    # 6c. 待办升级项（从 framework 相关 issue 关键词扫描）
    lines.append("### 6.3 待办框架升级项")
    lines.append("")
    pending = []
    for issue, decl in zip(issues, decls):
        if not decl:
            continue
        if decl.get("module") == "framework" and issue.get("state") == "open":
            num = issue["number"]
            t = normalize_type(decl.get("type", "standalone"))
            target = (decl.get("target") or decl.get("update") or issue["title"]).replace("|", "\\|")
            pending.append(f"[{t}] #{num} {target}")
    if pending:
        for item in pending:
            lines.append(f"- {item}")
    else:
        lines.append("_当前无 open 的 framework 升级项。_")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 7. 刷新指南 =====
    lines.append("## 九、刷新指南")
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
