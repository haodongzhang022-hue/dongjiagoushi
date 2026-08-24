# -*- coding: utf-8 -*-
"""
hello_team · 架构·测试 交付 — tests/test_hello_team.py
========================================================
测试矩阵（角色：架构·测试 交付，信号灯 🟢）：
  T1 小组A greet 核心：常规问候生成
  T2 跨小组数据互通：greet 消费小组B meta 的 team_id
  T3 小组B meta 元数据：team_count / framework_version
  T4 端到端整合：main.deliver 返回 delivered 状态
"""
import os
import sys

# 复用 main.py 的路径处理
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", "team_a"))
sys.path.insert(0, os.path.join(_HERE, "..", "team_b"))

from team_a.greet import greet
from team_b.meta import load_team_meta, TEAM_META
from main import deliver


def test_greet_core():
    """T1 小组A：greet 生成常规问候。"""
    msg = greet("张浩东")
    assert "你好，张浩东" in msg, f"greet 输出异常: {msg}"


def test_cross_team_data_flow():
    """T2 跨小组数据互通：greet 消费小组B的 team_id。"""
    msg = greet("测试员", meta_loader=lambda: "team_b")
    assert "team_b" in msg, f"跨组数据未互通: {msg}"


def test_meta_data():
    """T3 小组B：meta 元数据完整。"""
    meta = load_team_meta()
    assert meta["team_count"] == 2, f"小组数异常: {meta['team_count']}"
    assert "framework_version" in meta
    assert TEAM_META["teams"][0]["team_id"] == "team_a"


def test_end_to_end():
    """T4 端到端整合：main.deliver 返回 delivered。"""
    result = deliver()
    assert result["status"] == "delivered"
    assert "团队标识" in result["greeting"]


def run_all():
    """本地自测入口，输出信号灯。"""
    cases = [
        ("T1 greet核心", test_greet_core),
        ("T2 跨组数据互通", test_cross_team_data_flow),
        ("T3 meta元数据", test_meta_data),
        ("T4 端到端整合", test_end_to_end),
    ]
    passed = 0
    for name, fn in cases:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
    print(f"\n信号灯：{passed}/{len(cases)} 通过")
    return passed == len(cases)


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
