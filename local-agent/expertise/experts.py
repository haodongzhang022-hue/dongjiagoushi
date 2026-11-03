# -*- coding: utf-8 -*-
"""
行业/岗位专家层消费者（expertise.experts · 消费 hanghangchuzhuangyuan，不重造轮子）
================================================================================
定位：**通用架构师不得凭空宣称「我懂所有行业」**。行业划分、岗位职责、能力标签
的唯一事实源在 `dongdongxiaozu/hanghangchuzhuangyuan`；本模块只做三件事：

  1. **取件**：按配置路径（或环境变量 EXPERT_LAYER_ROOT）加载其注册表；
  2. **判定**：把一句需求判定为 (行业单元, 岗位列表)，给出**置信度与来源**；
  3. **降级**：专家层不可用时显式返回 `status=unverified`，**绝不伪造命中**
     （见 AGENTS.md 唯一事实纪律：判不出来 ≠ 通过）。

跨平台注意：hanghang 的 `engine/__init__.py` 聚合导入了依赖 POSIX `fcntl` 的
`hanghang.state` 包，在 Windows 上整包 import 会失败。本模块**刻意按文件路径
直接加载 models/registry**（纯数据层、零 POSIX 依赖），既不修改对方仓库，也不
假设对方能整包导入 —— 这是\"只消费稳定接口\"而非\"依赖其全部实现\"。
"""
from __future__ import annotations

import glob
import importlib.util
import os
import sys
from datetime import datetime, timezone

from .spec import EXPERT_SOURCES

# ---------------------------------------------------------------------------
# 一、定位专家层（多路径探测，不写死单一路径）
# ---------------------------------------------------------------------------
def _candidate_roots():
    """按优先级探测 hanghangchuzhuangyuan 的本地副本根目录。

    允许通过环境变量显式指定（CI / 云端 / 异构机器通用），否则走常见布局。
    """
    roots = []
    env = os.environ.get("EXPERT_LAYER_ROOT")
    if env:
        roots.append(env)
    here = os.path.dirname(os.path.abspath(__file__))          # local-agent/expertise
    local_agent = os.path.dirname(here)                         # local-agent
    repo_root = os.path.dirname(local_agent)                    # dongjiagoushi
    parent = os.path.dirname(repo_root)
    # 常见同级布局：<parent>/hanghangchuzhuangyuan、<parent>/mirror/hanghangchuzhuangyuan
    roots.extend([
        os.path.join(parent, "hanghangchuzhuangyuan"),
        os.path.join(parent, "mirror", "hanghangchuzhuangyuan"),
        os.path.join(repo_root, "hanghangchuzhuangyuan"),
    ])
    globs = [
        os.path.join(parent, "*", "mirror", "hanghangchuzhuangyuan"),
        "E:/CNBcool/mirror/hanghangchuzhuangyuan",
        "/workspace/*/hanghangchuzhuangyuan",
    ]
    for pattern in globs:
        try:
            roots.extend(glob.glob(pattern))
        except Exception:  # noqa: BLE001
            continue
    return roots


def _load_module(name, path):
    """按文件路径加载模块（用于绕开对方包 __init__ 的 POSIX 依赖）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_engine_package(engine_dir, package_name="_hh_engine_offline"):
    """把 hanghang 的 `engine` 目录作为**离线包**加载到独立命名空间。

    为什么不用 `import hanghang.engine`：其 `__init__.py` 聚合导入了
    `hanghang.state`（依赖 POSIX `fcntl`），在 Windows / 精简环境整包 import 会失败。
    这里用 importlib 构造一个最小包（带 `__path__`），只让 `models.py` / `registry.py`
    在其内部做相对导入 —— **不修改对方仓库**，也不假设对方整包可导入。
    """
    import types

    pkg_name = package_name
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [engine_dir]           # 关键：让相对导入能找到同级模块
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg

    _load_module(f"{pkg_name}.models", os.path.join(engine_dir, "models.py"))
    registry_mod = _load_module(f"{pkg_name}.registry", os.path.join(engine_dir, "registry.py"))
    if not hasattr(registry_mod, "Registry"):
        raise ImportError("registry.py 未导出 Registry")
    return registry_mod


# ---------------------------------------------------------------------------
# 二、专家层句柄（加载失败 = 显式不可用，不抛穿业务链路）
# ---------------------------------------------------------------------------
class IndustryExpertLayer:
    """行业/岗位专家层句柄。

    用法：
        layer = IndustryExpertLayer()
        layer.available            # bool
        layer.resolve("给律所做合同审查系统")
        # -> {"status": "matched", "unit_id": ..., "industry": ..., "roles": [...],
        #     "evidence": [...], "source": ...}
    """

    def __init__(self, root=None, search_paths=None):
        self.root = None
        self.registry = None
        self.error = None
        self.source = EXPERT_SOURCES["industry"]["repo"]
        self._load(root=root, search_paths=search_paths)

    # -- 加载 ---------------------------------------------------------------
    def _load(self, root=None, search_paths=None):
        roots = [root] if root else _candidate_roots()
        for candidate in roots:
            if not candidate:
                continue
            index = os.path.join(candidate, "data", "unit-index.yaml")
            register = os.path.join(candidate, "data", "industry-register.yaml")
            engine_dir = os.path.join(candidate, "src", "hanghang", "engine")
            if not os.path.exists(index) and not os.path.exists(register):
                continue
            if not os.path.isdir(engine_dir):
                continue
            try:
                registry_mod = _load_engine_package(engine_dir)
                paths = search_paths or [os.path.join(candidate, "data")]
                self.registry = registry_mod.Registry(paths)
                self.root = candidate
                self.error = None
                return
            except Exception as exc:  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}"
                continue
        if self.error is None:
            self.error = "未找到 hanghangchuzhuangyuan 本地副本（设置 EXPERT_LAYER_ROOT 可显式指定）"

    # -- 状态 ---------------------------------------------------------------
    @property
    def available(self):
        return self.registry is not None

    def status(self):
        return {
            "available": self.available,
            "root": self.root,
            "source": self.source,
            "error": self.error,
            "unit_count": len(self._units()) if self.available else 0,
        }

    # -- 查询 ---------------------------------------------------------------
    def _units(self):
        if not self.available:
            return []
        try:
            return list(self.registry.all_units())
        except Exception:  # noqa: BLE001
            return []

    def industries(self):
        """返回已注册行业清单（结构性数据，恒定可答）。"""
        out = []
        for unit in self._units():
            out.append({
                "unit_id": getattr(unit, "unit_id", ""),
                "industry": getattr(unit, "industry", ""),
                "roles": [getattr(r, "name", "") for r in getattr(unit, "roles", [])],
            })
        return out

    def resolve(self, text):
        """把需求文本判定为 (行业单元, 岗位列表)。

        判定口径（确定性，词面**双向**包含匹配）：
          - 岗位关键词命中：`kw in text`（需求里出现岗位触发词）；
          - 行业名/别名命中：`text in alias`（需求整体落在该行业域内）或 `alias in text`。
        双向原因：中文需求常只写「帮我做个登录模块」，此处行业名本身不在文本中，
        应回落到**当前行业域**（由调用方给出 default_unit），而不是伪造命中。
        """
        if not self.available:
            return {
                "status": "unverified",
                "reason": self.error,
                "source": self.source,
            }
        try:
            text_l = (text or "").lower()
            best = None
            for unit in self._units():
                unit_id = getattr(unit, "unit_id", "")
                industry = getattr(unit, "industry", "")
                aliases = [str(a).lower() for a in (getattr(unit, "industry_alias", []) or [])]
                aliases.append(str(industry).lower())
                alias_hits = []
                for alias in aliases:
                    if not alias:
                        continue
                    if alias in text_l or text_l in alias:
                        alias_hits.append(alias)
                role_hits = []
                for role in getattr(unit, "roles", []):
                    name = getattr(role, "name", "")
                    kws = [str(k).lower() for k in (getattr(role, "keywords", []) or [])]
                    hit = [kw for kw in kws if kw and kw in text_l]
                    if hit:
                        role_hits.append({"role": name, "keywords": hit})
                score = len(alias_hits) * 2 + sum(len(h["keywords"]) for h in role_hits)
                if score <= 0:
                    continue
                cand = {
                    "unit_id": unit_id,
                    "industry": industry,
                    "alias_hits": alias_hits,
                    "roles": role_hits,
                    "score": score,
                }
                if best is None or cand["score"] > best["score"]:
                    best = cand
            if best is None:
                return {
                    "status": "no_match",
                    "reason": "需求文本未命中任何已注册行业/岗位关键词",
                    "source": self.source,
                    "unit_count": len(self._units()),
                }
            total = best["score"]
            confidence = min(1.0, total / 6.0)
            best.update({
                "status": "matched",
                "confidence": round(confidence, 3),
                "source": self.source,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            })
            return best
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "unverified",
                "reason": f"{type(exc).__name__}: {exc}",
                "source": self.source,
            }

    def capability_of_role(self, role_name):
        """跨行业查某个岗位名在哪些行业里存在（广度维度证据）。"""
        hits = []
        for unit in self._units():
            for role in getattr(unit, "roles", []):
                if getattr(role, "name", "") == role_name:
                    hits.append({
                        "unit_id": getattr(unit, "unit_id", ""),
                        "industry": getattr(unit, "industry", ""),
                        "description": getattr(role, "description", ""),
                    })
        return hits
