# -*- coding: utf-8 -*-
"""本地⇄云端 · 真实传输层（CnbTransport）+ 真实本地执行器（ShellExecutor）。

补齐 `entries.bridge` 的两个 mock 口子（Issue #105 三.6 的欠债）：

    bridge.request_cloud_dev(transport=None)   → 默认 mock，**不发任何请求**
    bridge.local_test_first(executor=None)     → 默认 mock，**不跑任何测试**

本模块给这两处提供**真实现**，并且刻意做成「可注入的最小契约」，
不改 bridge 的核心状态机：

    transport: {"name": str, "send": fn(handle)->dict, "ack": fn(handle)->dict}
    executor:  {"name": str, "run": fn(scripts)->dict}

## 为什么必须解析 cnb.js 而不是直接调 `cnb`

Windows 上 `cnb` 是 `cnb.ps1` / `cnb.cmd` 包装脚本，`subprocess.run(["cnb", ...])`
直接抛 `FileNotFoundError`（WinError 2，本机实测）。而 `dispatch_engine._create_issue`
恰好 `except (TimeoutExpired, FileNotFoundError): return None` —— **静默失败**。
所以这里统一走「找到 node + cnb-cli/bin/cnb.js」再调用，两个平台都成立。

## 契约上的一个硬约束

`send()` 只有在**真的拿到了平台回执**（Issue 编号）时才返回 `ok`。
拿不到就抛错，由 bridge 记成 `pending` + `send_error` ——
**绝不用构造值冒充「已投递」**（这正是 mock 的问题：`sim-issue` 看起来像成功）。
"""
import json
import os
import re
import shutil
import subprocess

#: cnb CLI 的常见落点（Windows npm 全局 / 类 Unix）
_CLI_CANDIDATES = (
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "nodejs", "cnb.cmd"),
    os.path.join(os.environ.get("APPDATA", ""), "npm", "cnb.cmd"),
    "/usr/local/bin/cnb",
    "/usr/bin/cnb",
)
#: cnb.js 相对 cnb.cmd 的位置（npm 全局目录结构）
_JS_REL = os.path.join("node_modules", "@cnbcool", "cnb-cli", "bin", "cnb.js")


def resolve_cnb_launcher():
    """返回可直接喂给 subprocess 的 argv 前缀，例如 `[node, .../cnb.js]`。

    解析顺序：`CNB_CLI_JS` 环境变量 → 已知落点推出 node+js → PATH 上的 cnb。
    都找不到时返回 `None`（调用方据此显式失败，而不是静默返回 None）。
    """
    js = os.environ.get("CNB_CLI_JS", "").strip()
    if not js or not os.path.exists(js):
        for cand in _CLI_CANDIDATES:
            if not cand:
                continue
            maybe_js = os.path.join(os.path.dirname(cand), _JS_REL)
            if os.path.exists(maybe_js):
                js = maybe_js
                break
    if js and os.path.exists(js):
        node = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(js))))), "node.exe")
        # 上面的推导只为取 npm 全局目录；拿不到就用 PATH 里的 node
        node = node if os.path.exists(node) else (shutil.which("node") or "node")
        return [node, js]
    exe = shutil.which("cnb")
    return [exe] if exe else None


def run_cnb(args, timeout=60, cwd=None):
    """跑一条 cnb 命令。返回 (rc, stdout, stderr)。找不到 CLI 时抛 RuntimeError。"""
    launcher = resolve_cnb_launcher()
    if not launcher:
        raise RuntimeError(
            "找不到 cnb CLI：设置 CNB_CLI_JS 指向 node_modules/@cnbcool/cnb-cli/bin/cnb.js，"
            "或确保 cnb 在 PATH 上")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run(launcher + list(args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout,
                       env=env, cwd=cwd)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def _parse_issue_number(stdout):
    """从 cnb CLI 输出里取 Issue 编号。CLI 默认吐 YAML，`--verbose` 才是 JSON。"""
    s = (stdout or "").strip()
    if not s:
        return None
    # JSON 形态
    try:
        start = s.find("{")
        if start >= 0:
            data = json.loads(s[start:])
            node = data.get("data", data)
            if isinstance(node, dict) and node.get("number") is not None:
                return int(node["number"])
    except Exception:                                    # noqa: BLE001
        pass
    # YAML 形态
    m = re.search(r'^\s*number:\s*"?(\d+)"?\s*$', s, re.M)
    return int(m.group(1)) if m else None


class CnbTransport(object):
    """把云开发请求**真的**发到 cnb.cool：在目标仓建一个 Issue 当云端锚点。

    为什么用 Issue 而不是直接调 NPC：NPC 的事件入口就是「Issue/PR 评论 @角色」，
    Issue 是那个事件的最小载体；同时它天然是**可核验的云端句柄**（有编号、有 URL），
    本地拿不回编号就等于没发出去。
    """

    name = "cnb"

    def __init__(self, repo, token=None, issue_body_tpl=None, dry_run=False):
        self.repo = repo
        self.token = token or os.environ.get("CNB_TOKEN") or None
        self.issue_body_tpl = issue_body_tpl
        self.dry_run = dry_run
        self.last_error = ""

    def _body(self, handle):
        if self.issue_body_tpl:
            return self.issue_body_tpl.format(**handle)
        return ("由本地中控（entries.bridge · CnbTransport）发起的云端开发请求。\n\n"
                "**任务**：{req}\n\n"
                "**桥接句柄**：`{handle_id}`\n"
                "**发起入口**：{entry}\n\n"
                "> 本地负责运行时与测试；云端承接可配合的部分。"
                "请回执 `[接单]` 并说明承接范围。").format(**handle)

    def send(self, handle):
        """建 Issue 并返回真实 cloud_ref。**拿不到编号就抛错**，不伪造成功。"""
        if self.dry_run:
            return {"ok": True, "status": "in_cloud_dev",
                    "cloud_ref": {"issue_id": "", "sent_via": "dry-run",
                                  "note": "dry-run：未真正建 Issue"}}
        title = "云端开发请求：{}".format(
            (handle.get("req") or "")[:60].replace("\n", " "))
        args = ["issues", "create-issue", "--repo", self.repo,
                "--title", title, "--body", self._body(handle)]
        if self.token:
            env_token = self.token
            os.environ.setdefault("CNB_TOKEN", env_token)
        rc, out, err = run_cnb(args, timeout=90)
        num = _parse_issue_number(out) or _parse_issue_number(err)
        if rc != 0 and num is None:
            self.last_error = (err or out or "").strip()[:300]
            raise RuntimeError("建 Issue 失败 rc={}: {}".format(rc, self.last_error))
        if num is None:
            self.last_error = (out or err or "").strip()[:300]
            raise RuntimeError("建 Issue 返回 0 但解析不到编号：{}".format(self.last_error))
        return {"ok": True, "status": "in_cloud_dev",
                "cloud_ref": {"issue_id": num, "sent_via": "cnb",
                              "repo": self.repo,
                              "url": "https://cnb.cool/{}/-/issues/{}".format(self.repo, num)}}

    def ack(self, handle):
        """云端已收下（collect 阶段回执）。当前不需要额外动作，留作扩展点。"""
        return {"ok": True, "note": "cnb transport: no-op ack"}


def resolve_bash():
    """挑一个**能正确处理 Windows 路径**的 bash。

    坑：`shutil.which("bash")` 在 Windows 上会先命中 `C:\\Windows\\system32\\bash.exe`
    （WSL）。WSL 的 bash 把 `E:\\CNBcool\\...` 里的 `\\` 当转义符吃掉，
    于是路径变成 `E:CNBcool_test...` → `No such file or directory`（实测 rc=127）。
    Git Bash 认得 Windows 路径，优先用它。
    """
    explicit = os.environ.get("BRIDGE_BASH", "").strip()
    if explicit and os.path.exists(explicit):
        return explicit
    for cand in (r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files\Git\usr\bin\bash.exe",
                 "/bin/bash", "/usr/bin/bash"):
        if os.path.exists(cand):
            return cand
    return shutil.which("bash") or "bash"


class ShellExecutor(object):
    """真实本地执行器：跑仓库自带信号灯（`bash tests/*.sh`）。

    云端建环境贵、本地 CPU 便宜 —— 这就是 `local_test_first` 要省的那笔钱，
    所以要真跑，不能只回一个 plan。
    """

    name = "shell"

    def __init__(self, cwd, timeout=1800, shell=None):
        self.cwd = cwd
        self.timeout = timeout
        self.shell = shell or resolve_bash()

    def _env(self):
        """执行环境：保证 `python3` 可用。

        仓内信号灯普遍写死 `python3`，而 Windows 上通常只有 `python`。
        **不往系统/conda 目录里塞文件**（那是污染），改为在系统临时目录
        造一个只含 `python3.exe` 别名的 shim 目录，临时插到 PATH 最前。
        """
        env = {**os.environ}
        if shutil.which("python3"):
            return env
        py = shutil.which("python") or shutil.which("python.exe")
        if not py:
            return env
        try:
            import tempfile
            bindir = os.path.join(tempfile.gettempdir(), "bridge-py3-shim")
            os.makedirs(bindir, exist_ok=True)
            alias = os.path.join(bindir, "python3.exe")
            if not os.path.exists(alias):
                shutil.copy2(py, alias)
            env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        except Exception:                            # noqa: BLE001
            env["PATH"] = os.path.dirname(py) + os.pathsep + env.get("PATH", "")
        return env

    def run(self, scripts):
        results = []
        for s in scripts:
            # 脚本名可能是裸名（test_x.sh）也可能带目录（tests/test_x.sh），两种都认
            cands = [s] if os.path.isabs(s) else [
                os.path.join(self.cwd, s),
                os.path.join(self.cwd, "tests", s),
            ]
            path = next((c for c in cands if os.path.exists(c)), None)
            if path is None:
                results.append({"script": s, "rc": -3, "ok": False,
                                "tail": ["找不到脚本：{}".format(s)]})
                continue
            try:
                r = subprocess.run([self.shell, path], cwd=self.cwd,
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=self.timeout, env=self._env())
                out = (r.stdout or "") + (r.stderr or "")
                tail = out.strip().splitlines()[-4:]
                results.append({"script": s, "rc": r.returncode,
                                "ok": r.returncode == 0, "tail": tail})
            except FileNotFoundError:
                results.append({"script": s, "rc": -1, "ok": False,
                                "tail": ["找不到 bash：本机未安装或不在 PATH"]})
            except subprocess.TimeoutExpired:
                results.append({"script": s, "rc": -2, "ok": False,
                                "tail": ["超时 {}".format(self.timeout)]})
        ok = bool(results) and all(r["ok"] for r in results)
        return {"ok": ok, "mode": "shell", "executed": results,
                "passed": sum(1 for r in results if r["ok"]),
                "failed": sum(1 for r in results if not r["ok"])}
