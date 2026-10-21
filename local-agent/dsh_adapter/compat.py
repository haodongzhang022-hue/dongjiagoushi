# -*- coding: utf-8 -*-
"""
dsh 版本兼容自检（dsh_adapter.compat · Python 侧）
====================================================
与 `dsh-adapter/src/compat.ts`（TS 侧）共享同一版本矩阵与 API 面表——
DeepSeek Harness 处于 0.x 技术预览期，minor/rc 间存在 schema/行为变化，
适配插件必须**声明并校验**目标版本面，杜绝"装上但工具不生效"的静默失效。

用法：
    python -m dsh_adapter.compat check 0.1.6-alpha.2
    python -m dsh_adapter.compat check --json 0.1.6-alpha.2
    python -m dsh_adapter.compat matrix
"""
import json
import re
import sys

# ---- 版本解析（兼容 0.1.6-alpha.2 / 0.1.5-rc.2 形态）----
_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([a-z]+)\.?(\d+))?", re.I)
_CHANNEL_WEIGHT = {"": 100, "rc": 90, "beta": 60, "alpha": 40}


def parse_version(raw):
    """解析语义化版本串；无法解析返回 None（不抛异常）。"""
    if not isinstance(raw, str):
        return None
    m = _SEMVER_RE.match(raw.strip())
    if not m:
        return None
    return {
        "major": int(m.group(1)), "minor": int(m.group(2)), "patch": int(m.group(3)),
        "channel": (m.group(4) or "").lower(),
        "rank": int(m.group(5)) if m.group(5) else 0,
        "raw": raw.strip(),
    }


def _key(v):
    return (v["major"], v["minor"], v["patch"],
            _CHANNEL_WEIGHT.get(v["channel"], 0), v["rank"])


def compare_version(a, b):
    """a > b → 1，a < b → -1，相等 0（None 排最前）。"""
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    ka, kb = _key(a), _key(b)
    return (ka > kb) - (ka < kb)


# ---- API 面表（唯一事实源，与 TS 侧一致）----
API_FACES = [
    {"id": "python-sdk", "since": "0.1.0-rc.2",
     "note": "Python SDK 主推：内嵌 SEA runtime，插件以 Python 侧挂载为主"},
    {"id": "cli-headless", "since": "0.1.1-rc.1",
     "note": "官方 CLI headless 模式（dsh --profile headless）"},
    {"id": "profile-bundle", "since": "0.1.2-rc.1",
     "note": "profile + 组合包分发格式：package.json 的 dsh.profile / dsh.bundle"},
    {"id": "cordis-all-plugin", "since": "0.1.5-rc.1",
     "note": "一切皆插件（Cordis）：服务/事件/副作用皆插件"},
    {"id": "defineTool", "since": "0.1.5-rc.1",
     "note": "ctx.tools.register(defineTool({...})) 为工具注册唯一入口"},
    {"id": "patch-overlay", "since": "0.1.6-alpha.1",
     "note": "有序 patch overlay（--patch / cordis.patch.yml）按 id 定位替换 config"},
    {"id": "output-render", "since": "0.2.0-alpha.1",
     "note": "defineTool 的 output.render(args, value) 成为必调渲染钩子：缺它定义仍能构造，"
             "但每次调用都抛 TypeError（dsh-tools 0.0.1-rc.1 实测）——必须显式提供"},
    {"id": "bundles-manifest", "since": "0.2.0-rc.1",
     "note": "profile 由 dsh.profile.bundles 有序组合包 + patch 层叠加（dsh 0.2.x 契约）"},
]

# 测试矩阵（适配目标的"当前"值）
DSH_COMPAT = {
    "min_version": "0.1.5-rc.1",
    "target_version": "0.2.1-rc.2",
    # ★ 2026-10-21（Issue #202 收尾）只用真实 dsh-tools 0.0.1-rc.1 实测过 output.render
    #   必调面；0.1.x 一代没拿真实包跑过，故不再列「已测」（保留在 minVersion 之上，
    #   走降级模式 + 版本闸门自检），避免再次出现"测试全绿、真实运行时一用就崩"。
    "tested_against": ["0.2.1-rc.2", "0.2.1-alpha.5"],
    "required_faces": ["cordis-all-plugin", "defineTool", "profile-bundle"],
}


def api_faces_of(version):
    """给定版本 → 其具备的 API 面 id 清单。"""
    p = parse_version(version) if isinstance(version, str) else version
    if not p:
        return []
    return [f["id"] for f in API_FACES
            if compare_version(p, parse_version(f["since"])) >= 0]


def check_version(version):
    """兼容性判定（确定性）：ok / degrade / incompatible。"""
    parsed = parse_version(version)
    faces = api_faces_of(parsed)
    missing = [f for f in DSH_COMPAT["required_faces"] if f not in faces]

    if not parsed:
        return {"state": "incompatible", "version": str(version), "faces": faces,
                "missing_faces": list(DSH_COMPAT["required_faces"]),
                "message": '无法解析 dsh 版本 "%s"，拒绝静默加载' % version}
    if compare_version(parsed, parse_version(DSH_COMPAT["min_version"])) < 0:
        return {"state": "incompatible", "version": version, "faces": faces,
                "missing_faces": missing,
                "message": "dsh %s 低于最低要求 %s，请升级" % (
                    version, DSH_COMPAT["min_version"])}
    if missing:
        return {"state": "incompatible", "version": version, "faces": faces,
                "missing_faces": missing,
                "message": "dsh %s 缺少必需 API 面：%s" % (version, ", ".join(missing))}
    if version not in DSH_COMPAT["tested_against"]:
        return {"state": "degrade", "version": version, "faces": faces,
                "missing_faces": missing,
                "message": "dsh %s 具备所需 API 面但未在测试矩阵内（已实测：%s），按降级模式加载"
                   % (version, ", ".join(DSH_COMPAT["tested_against"]))}
    return {"state": "ok", "version": version, "faces": faces, "missing_faces": missing,
            "message": "dsh %s 兼容（API 面：%s）" % (version, ", ".join(faces))}


def compat_matrix():
    """返回完整兼容矩阵（供报告 / 测试 / 文档生成）。"""
    return {
        "module": "dsh-adapter",
        "min_version": DSH_COMPAT["min_version"],
        "target_version": DSH_COMPAT["target_version"],
        "tested_against": DSH_COMPAT["tested_against"],
        "required_faces": DSH_COMPAT["required_faces"],
        "api_faces": API_FACES,
        "matrix": {v: check_version(v)["state"]
                   for v in ["0.2.1-rc.2", "0.2.1-alpha.5", "0.1.6-alpha.2",
                             "0.1.5-rc.2", "0.1.5-rc.1",
                             "0.1.3-alpha.2", "0.1.2-rc.1", "0.0.1-rc.1"]},
    }


def _main(argv):
    argv = list(argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    cmd = argv[0] if argv else "matrix"

    if cmd == "check":
        ver = argv[1] if len(argv) > 1 else DSH_COMPAT["target_version"]
        r = check_version(ver)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["state"] != "incompatible" else 1
    if cmd == "matrix":
        print(json.dumps(compat_matrix(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps({"ok": False, "error": "未知命令 %s" % cmd,
                      "available": ["check", "matrix"]}, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
