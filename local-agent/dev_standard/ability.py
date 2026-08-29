# -*- coding: utf-8 -*-
"""
开发规范全员能力（StandardAbility · Issue #83）
=================================================
把「开发规范遵循」封装为**每个 agent 可复用的通用能力**，默认挂载到 BaseRole，
让任何开发/评审/测试 agent 都能：
  - 查询规范条目（按级别/类别/强制时机分层）；
  - 程序化检查合规性（确定性，非 LLM 判断）；
  - 获取某开发阶段的强制规范清单；
  - 生成合规报告并留痕（供评审/测试核验）。

设计（对齐用户"本身应该是一个体系，不应该是孤立的点"）：
  - 独立模块（local-agent/dev-standard/）可各处引用；
  - 深度绑定开发过程（enforce_at 强制时机）；
  - 能力挂载到 BaseRole（与 Dispatch/Handle/Depth/Label/DevTeam 一致）；
  - 程序化 CLI / MCP 双接口（脚本/CI 可调用）。

用法（任意角色实例，BaseRole 已挂载）：
  role.list_standards(level="L1")            # 列出规范
  role.check_standard({"pr_info": {...}})    # 检查合规性
  role.get_enforced_specs("pre_pr")          # 某阶段强制规范
  role.report_compliance("pr-1", results)    # 合规报告并留痕
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class StandardAbility:
    """开发规范全员能力。

    owner 绑定所属 agent（角色名/实例），合规留痕归因到该 agent。
    """

    def __init__(self, owner=None):
        self.owner = owner
        self._owner_name = getattr(owner, "name", "") or (owner if isinstance(owner, str) else "系统")

    # ---- 规范查询（全员开放）----
    def list_standards(self, level=None, category=None):
        """列出规范条目（按级别/类别过滤）。"""
        from dev_standard import specs
        return specs.list_specs(level=level, category=category)

    def get_standard(self, spec_id):
        """获取单条规范详情。"""
        from dev_standard import specs
        return specs.get_spec(spec_id)

    def get_enforced_specs(self, stage):
        """获取某开发阶段的强制规范清单。"""
        from dev_standard import specs
        return specs.specs_by_enforce_at(stage)

    def standards_summary(self):
        """规范注册表概览（二级信息）。"""
        from dev_standard import specs
        return specs.summary()

    # ---- 合规检查（确定性）----
    def check_standard(self, target, spec_ids=None):
        """检查合规性（确定性检查器，非 LLM 判断）。"""
        from dev_standard.checker import StandardChecker
        return StandardChecker().check(target, spec_ids=spec_ids)

    def check_pr(self, pr_info):
        """PR 规范检查。"""
        from dev_standard.checker import StandardChecker
        return StandardChecker().check_pr(pr_info)

    def check_code(self, code_file, repo_path=""):
        """代码规范检查。"""
        from dev_standard.checker import StandardChecker
        return StandardChecker().check_code(code_file, repo_path=repo_path)

    def check_process(self, issue_info):
        """流程规范检查（Issue 声明/留痕/进度尺）。"""
        from dev_standard.checker import StandardChecker
        return StandardChecker().check_process(issue_info)

    def check_deliver(self, deliver_info):
        """交付规范检查（自测上报/变更范围）。"""
        from dev_standard.checker import StandardChecker
        return StandardChecker().check_deliver(deliver_info)

    # ---- 合规报告 + 留痕 ----
    def report_compliance(self, entity, results, format="json"):
        """生成合规报告（并尝试留痕到 archives）。"""
        from dev_standard.checker import StandardChecker
        report = StandardChecker().report(results, format=format)
        # 尝试留痕（不阻断——若环境无 DB 则仅返回报告）
        try:
            from data import get_repo  # noqa: F401
            trace = {"entity": entity, "operator": self._owner_name,
                     "overall": report.get("overall", "") if isinstance(report, dict) else report,
                     "results": results}
            self._trace_archive(entity, trace)
        except Exception:
            pass
        return report

    def _trace_archive(self, entity, trace):
        """写 archives（kind=standard_compliance）留痕，可回溯。"""
        try:
            from data.archives import write_archive  # noqa: F401
            write_archive(entity=entity, kind="standard_compliance",
                          operator=self._owner_name, payload=trace)
        except Exception:
            pass  # 留痕失败不阻断核心检查

    def capability(self):
        """返回本能力声明。"""
        return {
            "standard_ability": {
                "desc": "开发规范全员能力（确定性检查 + 阶段强制清单 + 合规留痕）",
                "methods": [
                    "list_standards / get_standard / get_enforced_specs / standards_summary",
                    "check_standard / check_pr / check_code / check_process / check_deliver",
                    "report_compliance",
                ],
                "rule": "开发/评审/测试在 enforce_at 阶段必须查询并遵循强制规范",
            }
        }
