#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 评论流统一入口信号灯（Issue #166 · 默认全量读，杜绝 page_size=10 静默截断）
# 断言集见同目录 test_comment_stream.py（8 组：默认全量 / 裸调 RED / 元信息 /
# has_receipt 读取侧 / 参数与翻页上限 / 双轨 receipt_verify / CLI 核回执）。
set -e
cd "$(dirname "$0")/.."
PY=python3
$PY tests/test_comment_stream.py
