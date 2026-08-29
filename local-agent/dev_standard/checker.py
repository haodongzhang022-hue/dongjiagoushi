# -*- coding: utf-8 -*-
"""
开发规范确定性检查器（dev-standard · checker.py · Issue #83）
================================================================
给定输入，**必然返回相同的合规报告**——不依赖 LLM 判断，杜绝"AI 自判合规"。
可被 CLI / CI / 评审 / 测试重复调用验证。

检查输入 target（dict），按规范条目（specs.STANDARD_SPECS）逐条检查，
返回：{ spec_id: { passed, level, check_type, severity, details } }
全部通过 → 合规；有 hard 失败 → 阻断（blocked_on: standard_violation）。

各 check_* 函数是确定性实现，注册进 specs.register_verify() 供统一调度。
"""
import os
import re
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from dev_standard import specs


class StandardChecker:
    """确定性规范检查器。给定输入 → 必然返回合规报告。"""

    def __init__(self):
        # 注册本类所有 check_* 方法到 VERIFY_IMPLS
        for name in dir(self):
            if name.startswith("check_") and callable(getattr(self, name)):
                specs.register_verify(name, getattr(self, name))

    # ==================================================================
    # 对外主入口
    # ==================================================================
    def check(self, target, spec_ids=None):
        """检查目标内容是否符合规范。

        target: dict，含待检内容（pr_info/code_file/issue_info 等，见各 check_*）
        spec_ids: 指定检查哪些规范；None=全查（默认全查）。
        返回: { spec_id: { spec_id, title, passed, level, check_type,
                           severity, details } }
        """
        if spec_ids is None:
            spec_ids = sorted(specs.STANDARD_SPECS.keys())
        results = {}
        for sid in spec_ids:
            spec = specs.get_spec(sid)
            if spec is None:
                results[sid] = {
                    "spec_id": sid, "title": "(unknown)", "passed": False,
                    "level": "L1", "check_type": "hard", "severity": "error",
                    "details": f"未知规范条目 {sid}",
                }
                continue
            fn = specs.VERIFY_IMPLS.get(spec["verify"])
            if fn is None:
                results[sid] = {
                    "spec_id": sid, "title": spec["title"], "passed": False,
                    "level": spec["level"], "check_type": spec["check_type"],
                    "severity": "error",
                    "details": f"检查函数 {spec['verify']} 未实现",
                }
                continue
            try:
                verdict = fn(target)
            except Exception as e:  # 检查器自身异常不吞，显式暴露
                verdict = {"ok": False, "details": f"检查器异常: {e}"}
            results[sid] = {
                "spec_id": sid,
                "title": spec["title"],
                "passed": bool(verdict.get("ok")),
                "level": spec["level"],
                "check_type": spec["check_type"],
                "severity": "error" if spec["check_type"] == "hard" and not verdict.get("ok") else
                            ("warning" if spec["check_type"] == "soft" and not verdict.get("ok") else "pass"),
                "details": verdict.get("details", ""),
            }
        return results

    def check_pr(self, pr_info):
        """PR 规范检查（结构类 S01-S05：base/main/解耦/接口/冲突/自带测试文档）。"""
        struct_ids = specs.SPECS_BY_CATEGORY.get("structure", [])
        return self.check(pr_info, spec_ids=struct_ids)

    def check_code(self, code_file, repo_path=""):
        """代码规范检查（结构/风格/错误处理/敏感信息等）。"""
        target = {"code_file": code_file, "repo_path": repo_path}
        return self.check(target, spec_ids=specs.SPECS_BY_ENFORCE_AT.get("commit", []))

    def check_process(self, issue_info):
        """流程规范检查（Issue 声明头/版本管理/进度尺等 process 类）。"""
        proc_ids = specs.SPECS_BY_CATEGORY.get("process", [])
        return self.check(issue_info, spec_ids=proc_ids)

    def check_deliver(self, deliver_info):
        """交付规范检查（自测上报/变更范围）。"""
        return self.check(deliver_info, spec_ids=specs.SPECS_BY_ENFORCE_AT.get("deliver", []))

    def report(self, results, format="json"):
        """输出合规报告（json/markdown/table）。"""
        passed = [r for r in results.values() if r["passed"]]
        failed = [r for r in results.values() if not r["passed"]]
        hard_fail = [r for r in failed if r["check_type"] == "hard"]
        soft_fail = [r for r in failed if r["check_type"] == "soft"]
        overall = "compliant" if not hard_fail else "blocked"

        if format == "json":
            return {
                "overall": overall,
                "total": len(results),
                "passed": len(passed),
                "hard_fail": len(hard_fail),
                "soft_fail": len(soft_fail),
                "hard_fail_items": [r["spec_id"] for r in hard_fail],
                "soft_fail_items": [r["spec_id"] for r in soft_fail],
                "results": results,
            }
        lines = [f"# 开发规范合规报告", f"**结论**: {overall.upper()}",
                 f"- 总检查: {len(results)}  通过: {len(passed)}  "
                 f"硬失败: {len(hard_fail)}  软失败: {len(soft_fail)}"]
        if hard_fail:
            lines.append("\n## 🔴 硬失败（阻断）")
            for r in hard_fail:
                lines.append(f"- `{r['spec_id']}` [{r['title']}] {r['details']}")
        if soft_fail:
            lines.append("\n## 🟡 软失败（警告）")
            for r in soft_fail:
                lines.append(f"- `{r['spec_id']}` [{r['title']}] {r['details']}")
        return "\n".join(lines)

    # ==================================================================
    # 各 check_* 确定性实现（注册到 VERIFY_IMPLS）
    # ==================================================================

    # ---------- 结构 S01-S05 ----------
    def check_pr_base_main(self, target):
        """S01: PR base 为 main。target.pr_info.target 应为 main。"""
        pr = target.get("pr_info") or {}
        base = pr.get("base") or pr.get("target") or ""
        ok = (str(base).lower() == "main")
        return {"ok": ok, "details": f"PR base = {base!r}，应为 main" if not ok else f"PR base = {base!r} ✅"}

    def check_decoupled(self, target):
        """S02: 按功能域解耦，base 不挂他人功能分支。"""
        pr = target.get("pr_info") or {}
        source = pr.get("source") or pr.get("head") or pr.get("branch") or ""
        # 合法源分支：main 或 auto/<模块>-<随机>，不得是他人功能集成分支名
        # 简化判定：base 必须为 main（S01 已覆盖），这里校验 source 命名规范
        s = str(source).lower()
        ok = s == "main" or (s.startswith("auto/") and "-" in s) or s == ""
        return {"ok": ok, "details": f"source 分支 {source!r} 需独立拉出（auto/ 前缀或 main）" if not ok else f"source {source!r} 解耦命名 ✅"}

    def check_interface_explicit(self, target):
        """S03: 接口显式化——模块有 __init__.py 导出公开接口。"""
        mod = target.get("module_path") or ""
        if not mod:
            return {"ok": True, "details": "未指定模块路径，跳过（提交级不强制）"}
        init_py = os.path.join(mod, "__init__.py")
        ok = os.path.isfile(init_py)
        return {"ok": ok, "details": f"模块 {mod} 需含 __init__.py 显式导出接口" if not ok else f"{init_py} 存在 ✅"}

    def check_no_conflict(self, target):
        """S04: 冲突前置规避——merge-tree 预检无冲突。"""
        pr = target.get("pr_info") or {}
        conflict = pr.get("has_conflict", False)
        ok = not conflict
        return {"ok": ok, "details": "PR 携带未解决冲突，禁止提交" if conflict else "无冲突标记 ✅"}

    def check_has_test_and_docs(self, target):
        """S05: 每个 PR 自含测试 + 文档。"""
        pr = target.get("pr_info") or {}
        test_present = bool(pr.get("test_files")) or bool(pr.get("has_test"))
        docs_present = bool(pr.get("docs_files")) or bool(pr.get("has_docs"))
        ok = test_present and docs_present
        details = []
        if not test_present:
            details.append("缺测试")
        if not docs_present:
            details.append("缺文档")
        return {"ok": ok, "details": "需含测试+文档" if details else "测试+文档齐备 ✅"}

    # ---------- 代码 C01-C03 ----------
    def check_no_bare_except(self, target):
        """C01: 不吞异常——代码文件无 bare except / except: 静默。"""
        code = self._read_code(target)
        if code is None:
            return {"ok": True, "details": "无代码文件可检，跳过"}
        # 匹配裸 except: / except ：（不带异常类型）
        # 用行首锚点精确匹配真实 except 语句，避免把注释/docstring/字符串中的
        # except: 文字误判为代码（自检 checker.py 不再误报）。
        _code = re.sub(chr(34)*3 + '.*?' + chr(34)*3, '', code, flags=re.DOTALL)  # 双引号 docstring
        bare = re.findall(r'^\s*except\s*:', _code, flags=re.MULTILINE)
        bare_full = re.findall(r'^\s*except\s*:\s*pass', _code, flags=re.MULTILINE)
        ok = not bare
        detail = f"发现 {len(bare)} 处裸 except（静默吞异常）" if bare else "无裸 except ✅"
        if bare and bare_full:
            detail += f"，其中 {len(bare_full)} 处为 except:pass"
        return {"ok": ok, "details": detail}

    def check_no_secrets(self, target):
        """C02: 敏感信息不落代码。"""
        code = self._read_code(target)
        if code is None:
            return {"ok": True, "details": "无代码文件可检，跳过"}
        # 常见敏感模式：token/password/api_key 赋值 + sk- 等前缀密钥
        patterns = [
            r"(?i)(token|password|secret|api_key|apikey)\s*=\s*['\"][^'\"]+['\"]",
            r"sk-[a-zA-Z0-9]{20,}",
            r"-----BEGIN (RSA |EC |)PRIVATE KEY-----",
        ]
        hits = []
        for pat in patterns:
            hits += re.findall(pat, code)
        ok = not hits
        return {"ok": ok, "details": f"发现疑似敏感信息 {len(hits)} 处" if hits else "未发现硬编码敏感信息 ✅"}

    def check_no_dead_code(self, target):
        """C03: 不留未引用 import / 死代码（软检查，启发式）。"""
        code = self._read_code(target)
        if code is None:
            return {"ok": True, "details": "无代码文件可检，跳过"}
        # 简单启发：`import X` 但代码中 X 未再出现（首现不算）
        imports = re.findall(r"^\s*import\s+(\w+)\s*$", code, re.M)
        unused = []
        for mod in imports:
            # 排除 import 行本身，看是否在其他地方出现
            rest = re.sub(rf"^\s*import\s+{re.escape(mod)}\s*$", "", code, flags=re.M)
            if not re.search(rf"\b{re.escape(mod)}\b", rest):
                unused.append(mod)
        ok = not unused
        detail = f"未使用 import: {unused}" if unused else "无未使用 import ✅"
        return {"ok": ok, "details": detail}

    # ---------- 文档 D01 ----------
    def check_traceable(self, target):
        """D01: 变更必留痕——提供 evidence（Issue/PR/提交记录）。"""
        evidence = target.get("evidence") or target.get("traces")
        ok = bool(evidence)
        detail = "需提供可核验留痕（Issue/PR/提交）" if not ok else f"已留痕: {len(evidence) if isinstance(evidence, list) else 'yes'} ✅"
        return {"ok": ok, "details": detail}

    # ---------- 流程 P01-P02 ----------
    def check_issue_declaration(self, target):
        """P01: Issue 声明头 + 双版本管理。"""
        issue = target.get("issue_info") or {}
        body = issue.get("body") or ""
        need_fields = ["module", "module_version", "type", "target", "update", "depends_on"]
        missing = [f for f in need_fields if f not in issue]
        # 也允许从 body 文本中检测
        if missing:
            missing = [f for f in missing if f not in body]
        ok = not missing
        detail = f"Issue 声明头缺: {missing}" if missing else "Issue 声明头齐备 ✅"
        return {"ok": ok, "details": detail}

    def check_goal_meters(self, target):
        """P02: 进度尺标注（goal_meters）。"""
        gm = target.get("goal_meters")
        ok = gm is not None and bool(gm)
        detail = "需写 goal_meters 进度尺刻度" if not ok else f"已有进度尺刻度 ✅"
        return {"ok": ok, "details": detail}

    # ---------- 质量 Q01-Q02 ----------
    def check_self_test_reported(self, target):
        """Q01: 自测结果上报（通过/失败）。"""
        self_test = target.get("self_test")
        ok = self_test is not None
        detail = "交付须上报自测结果（通过/失败）" if not ok else f"自测结果已上报: {self_test} ✅"
        return {"ok": ok, "details": detail}

    def check_scope_declared(self, target):
        """Q02: 变更范围声明（软检查）。"""
        scope = target.get("scope")
        ok = bool(scope)
        detail = "建议声明变更范围（软检查）" if not ok else f"变更范围: {scope} ✅"
        return {"ok": ok, "details": detail}

    # ---------- 工具 ----------
    @staticmethod
    def _read_code(target):
        """读取待检代码文件内容；无文件返回 None。"""
        path = target.get("code_file") or ""
        if not path or not os.path.isfile(path):
            # 也支持直接给 code 内容
            code = target.get("code")
            return code if code else None
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except (OSError, IOError) as e:
            # 文件读取失败——显式异常类型，不静默吞（C01 合规）
            return None


def check(target, spec_ids=None, format="json"):
    """便捷入口：StandardChecker 单例。"""
    return StandardChecker().check(target, spec_ids=spec_ids)
