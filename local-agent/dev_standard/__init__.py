# -*- coding: utf-8 -*-
"""
开发规范体系模块（dev-standard · Issue #83）
=============================================
把「开发规范」从零散人肉约定升级为**一套完整体系**：
  独立模块（可各处引用）+ 深度绑定开发过程 + 开发体系可快速遵循的机制 + 测试验证。

设计理念（用户拍板）：
  - **本身是一个体系，不是孤立的点**：规范定义层 + 检查器 + 全员能力 + 双接口 + rules 绑定；
  - **确定性检查**：规范检查器是确定性代码（非 LLM 判断），杜绝"AI 自判合规"；
  - **以使用效果为边界**：先搭建可用核心 → 测试是否稳定实现 → 再扩展绑定。

对外公开接口：
  - specs.STANDARD_SPECS        规范条目注册表（唯一事实源）
  - StandardChecker            确定性规范检查器
  - StandardAbility            全员能力（BaseRole 已挂载）
  - cli.main()                 CLI 接口（脚本/CI 调用）

用法（任意角色实例，BaseRole 已挂载）：
  role.list_standards(level="L1")          # 列出规范
  role.get_enforced_specs("pre_pr")        # 某阶段强制规范
  role.check_pr({"pr_info": {...}})        # PR 合规检查
  role.report_compliance("pr-1", results)  # 合规报告并留痕

CLI：
  python -m dev_standard.cli list
  python -m dev_standard.cli specs --level L1
  python -m dev_standard.cli check-pr --target main --source auto/x-1
  python -m dev_standard.cli check-code --file local-agent/x.py
  python -m dev_standard.cli check-all --target '{"pr_info": {...}}'
  python -m dev_standard.cli report --format json
"""
from .specs import STANDARD_SPECS, get_spec, list_specs, specs_by_enforce_at, summary
from .ability import StandardAbility

__all__ = [
    "StandardAbility",
    "STANDARD_SPECS",
    "get_spec",
    "list_specs",
    "specs_by_enforce_at",
    "summary",
]

# ---- M5 宿主接入（Issue #83 · 懒加载避免 -m 双导入告警）----
def get_host(operator="系统"):
    """获取 StandardMCPHost 宿主实例（懒加载，避免 __init__ 提前导入 host 模块）。

    供外部宿主/agent 运行时按需获取，与 mcp.call_mcp 等价但带宿主封装。
    """
    from .host import StandardMCPHost
    return StandardMCPHost(operator=operator)


__all__ = __all__ + ["get_host"]
