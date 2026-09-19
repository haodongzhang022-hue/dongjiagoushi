# -*- coding: utf-8 -*-
"""
CLI 兜底/占位后端。
====================
当没有可用模型后端时使用：
  - 它**不伪造**真实 LLM 推理结果；
  - 而是按角色输出契约生成「契约模板 + 占位说明」，并给出接入指引；
  - 同时可调用 `LLM_CLI` 环境变量指向的命令行工具（如 ollama run）做真实推理。
这样保证流水线骨架可跑通、可测试，又不违背"不假装执行"的诚实纪律。
"""
import os
import subprocess

from .base import LLMBackend, BackendRegistry


@BackendRegistry.register
class CliFallbackBackend(LLMBackend):
    name = "cli_fallback"

    def available(self):
        # 始终可用（占位/兜底）
        return True

    def call(self, system_prompt, user_input, role=None, **kw):
        cli = os.environ.get("LLM_CLI")
        if cli:
            try:
                proc = subprocess.run(
                    [cli, system_prompt + "\n\n" + user_input],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                return proc.stdout.strip() or proc.stderr.strip()
            except Exception as e:
                return f"[cli_fallback] CLI 调用失败: {e}"
        # 占位：明确标注未接入真实模型，输出契约骨架，不伪造推理结果
        return (
            "[占位执行·未接入真实模型] 已按角色输出契约生成模板。\n"
            "请配置 OPENAI_API_KEY 或 LLM_CLI 后启用真实推理。\n"
            f"role: {role or '(默认)'}\n"
            f"system_prompt 摘要: {system_prompt[:120]}...\n"
            f"user_input: {user_input[:200]}"
        )
