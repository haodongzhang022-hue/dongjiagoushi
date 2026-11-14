# -*- coding: utf-8 -*-
"""npc-model · NPC 模型选择能力（module npc-model v0.1.0）

解决「npc:go 的 model 写死会随组织可选模型列表漂移静默失效」的问题，
落地用户诉求：不写死模型、默认选大参数、兜底保证一直能通、模型更新可换。

唯一事实源：`.cnb/npc-models.yml`
"""
from .spec import ModelSpec, ModelPolicy, DEFAULT_CONFIG_PATH  # noqa: F401
from .selector import select_model, resolve, learn_from_error  # noqa: F401
