# -*- coding: utf-8 -*-
"""
调度中枢 · 多源适配器注册（sources）
====================================
用户拍板：**不能只支持一个源**——本地电脑 / 手机 / 虚拟机 / 沙盒 / 上位机都可能
作为终端参与。本模块提供多源适配器的注册与工厂，把每个外部终端接入 dispatcher：

  - `register_adapter(name, adapter)`：注册一个外部源适配器；
  - `build_sources(names=None)`：按需实例化一组适配器，供 Dispatcher 扫描；
  - `LocalHostAdapter`：本地电脑作为上位机/事件源的适配器（云端-本地协同主源，
    通过读取本地目录/文件/CLI 输出把本地事件推入 dispatcher）；
  - `preset_host_sources()`：预设多终端源（本地/手机/虚拟机/沙盒/上位机），
    上位机部分未解决好，先**预设功能**，之后接入。

设计：每个外部终端对应一个独立 ExternalAdapter 子类 + 一个 security 登记，
与 webhook 接收端互补（webhook 是被动收推送；adapter 是主动 poll）。
"""
from . import source as source_mod
from . import security

# 多源适配器注册表
_ADAPTERS = {}


def register_adapter(name, adapter):
    """注册一个外部源适配器（name 唯一，同 security.external_sources 对齐）。"""
    _ADAPTERS[name] = adapter
    return adapter


def get_adapter(name):
    return _ADAPTERS.get(name)


def list_adapters():
    return dict(_ADAPTERS)


class LocalHostAdapter(source_mod.ExternalAdapter):
    """本地电脑适配器（云端-本地协同的主源）。

    它把「本地电脑」作为一个外部事件源：通过一个可注入的 `local_provider`
    （读取本地目录/文件/CLI 输出/上位机队列等）拉取本地事件，推入 dispatcher。
    默认 provider 不实现（返回空），供接入方注入本地数据源；提供 `emit`
    便捷方法让本地进程主动上报事件（如本地守护脚本调用）。

    示例：
      adapter = LocalHostAdapter(name="local_pc")
      adapter.emit({"event_type": "requirement", "entity": "本地新需求",
                    "detail": {"note": "来自本地电脑"}})
    """

    def __init__(self, name="local_pc", local_provider=None, local_store=None):
        super().__init__(name)
        self._provider = local_provider
        # 本地事件暂存队列（内存），供 poll 消费
        self._local_store = local_store if local_store is not None else []

    def emit(self, raw_event):
        """本地进程主动上报一条事件（进入本地暂存，poll 时被消费）。"""
        if isinstance(raw_event, dict):
            raw_event.setdefault("source", self.name)
        self._local_store.append(raw_event)

    def poll(self):
        """轮询本地事件：消费 provider 或暂存队列，返回原始事件 list。"""
        events = []
        if self._provider:
            try:
                events.extend(self._provider() or [])
            except Exception:
                pass
        events.extend(self._local_store)
        self._local_store.clear()
        return events


def build_local_host(name="local_pc", local_provider=None, local_store=None):
    """构建并注册本地电脑适配器，同时登记 security 源（若无）。"""
    adapter = LocalHostAdapter(name, local_provider, local_store)
    register_adapter(name, adapter)
    if not security.get_source(name):
        security.register_source(name, ip_whitelist=["127.0.0.1", "::1", "0.0.0.0/0"],
                                 kind="host", meta='{"preset":true}')
    return adapter


def preset_host_sources(register_security=True):
    """预设多终端源适配器（本地/手机/虚拟机/沙盒/上位机）。

    用户拍板：不能只支持一个源；手机/虚拟机/沙盒都可能参与。上位机部分未解决好，
    先**预设功能**，之后接入。
    返回 {name: adapter}。
    """
    names = ["local_pc", "phone", "vm", "sandbox", "host_upper"]
    out = {}
    for name in names:
        adapter = LocalHostAdapter(name=name)
        register_adapter(name, adapter)
        out[name] = adapter
        if register_security and not security.get_source(name):
            security.register_source(name, ip_whitelist=[], kind="host",
                                     meta='{"preset":true}')
    return out


def build_sources(names=None):
    """按需实例化一组适配器（供 Dispatcher 扫描）。names 缺省时用已注册的。"""
    if names:
        return [get_adapter(n) for n in names if get_adapter(n)]
    return list(_ADAPTERS.values())
