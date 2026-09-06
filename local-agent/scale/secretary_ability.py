# -*- coding: utf-8 -*-
"""
秘书层动态扩展能力（SecretaryScaleAbility · Issue #100 决策①）
=============================================================
把「秘书层动态扩展机制」封装为秘书/经理层可调用的能力：识别该不该设秘书、
注册/卸载秘书服务、层间路由、越权护栏。

用法（秘书/经理角色，已挂载）：
  role.secretary_scale_suggest(domain, reuse_count=, scores=)   # 识别层
  role.register_secretary_service(domain, handoff_to=, ...)     # 注册层
  role.list_secretary_services()                                # 注册表
  role.secretary_route(request)                                 # 路由层
  role.secretary_guard(duty)                                    # 权限护栏
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


class SecretaryScaleAbility:
    def __init__(self, owner=None):
        self.owner = owner
        self._owner_name = getattr(owner, "name", "") or (owner if isinstance(owner, str) else "系统")

    def _m(self):
        from scale import secretary_scale as m
        return m

    # 识别层
    def secretary_scale_suggest(self, domain, reuse_count=0, scores=None,
                                requires_execution=False):
        return self._m().identify_secretary(
            domain, reuse_count=reuse_count, boundary_factor_scores=scores,
            requires_execution=requires_execution)

    # 注册层
    def register_secretary_service(self, domain, desc="", handoff_to="", reuse=0,
                                   interfaces=None):
        svc = self._m().register_secretary(domain, desc=desc, handoff_to=handoff_to,
                                           reuse=reuse, interfaces=interfaces)
        self._m().log("register", {"actor": self._owner_name, "domain": domain})
        return svc

    def unregister_secretary_service(self, domain):
        return self._m().unregister_secretary(domain)

    def activate_secretary_service(self, domain):
        return self._m().activate_secretary(domain)

    def drain_secretary_service(self, domain):
        return self._m().drain_secretary(domain)

    def list_secretary_services(self, status=None):
        return self._m().list_secretaries(status=status)

    def get_secretary_service(self, domain):
        return self._m().get_secretary(domain)

    # 路由层
    def secretary_route(self, request):
        return self._m().route_request(request)

    # 权限护栏
    def secretary_guard(self, duty):
        return self._m().guard(duty)

    # 留痕
    def secretary_scale_logs(self, limit=50):
        return self._m().recent_logs(limit=limit)

    def capability(self):
        return {
            "secretary_scale_ability": {
                "version": "0.1.0",
                "layers": ["识别(identify)", "注册(register)", "路由(route)"],
                "guard": "秘书只交接不执行，越权接终端任务即拦截",
            }
        }
