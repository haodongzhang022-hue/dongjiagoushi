# -*- coding: utf-8 -*-
"""
LocalWorker · 本地执行器
=========================
在本地批量执行被 HybridResourceRouter 判定为「纯 CPU 逻辑」的测试脚本
（云端已移除这些命令，故本地必须接住并跑出结果，云端只留 LLM 强相关）。

能力：
  - `plan()`：根据路由结果生成待本地执行的脚本清单；
  - `run()`：顺序批量执行本地脚本（含超时保护），逐条收集退出码/耗时/输出；
  - `run_all()`：把「判定 + 执行 + 汇总」一链路跑通，供 CLI/脚本直接调用。

本模块是**纯逻辑 + 子进程执行**，不依赖数据层，结果交由 sync 模块留痕。
"""
import os
import shlex
import subprocess
import time


def _to_wsl_path(path):
    """把 Windows 绝对路径转成 WSL 路径（E:\\a\\b → /mnt/e/a/b）。非 Windows 路径原样返回。"""
    if not path:
        return path
    path = path.replace("\\", "/")
    if len(path) >= 2 and path[1] == ":":
        drive = path[0].lower()
        return "/mnt/" + drive + path[2:]
    return path


def _wsl_popen_cmd(bash, script, cwd):
    """Windows + WSL bash 场景：cd 到 WSL 对应目录再执行（绕开路径不可见问题）。

    WSL bash 无法直接识别 C:/E:/ 盘符路径，先 cd 到 /mnt/<盘>/... 再跑相对脚本。
    返回最终 argv；脚本若是绝对 Windows 路径则一并转换为 WSL 路径。
    """
    wsl_cwd = _to_wsl_path(cwd)
    scr = script
    if os.path.isabs(script) and len(script) >= 2 and script[1] == ":":
        scr = _to_wsl_path(script)
    elif not os.path.isabs(script):
        scr = script  # 相对路径在 cd 之后自然可用
    return [bash, "-c", "cd '%s' && bash %s" % (wsl_cwd, scr)]


class LocalWorker(object):
    """本地批量测试执行器。"""

    def __init__(self, root_dir=None, timeout=300, dry_run=False):
        self.root_dir = root_dir or os.getcwd()
        self.timeout = timeout      # 单脚本超时（秒）
        self.dry_run = dry_run      # True：只打印不真跑（CI 演练用）

    # ---------- 计划 ----------
    def plan(self, local_scripts):
        """把 local 脚本清单转成可执行命令清单（含路径解析）。"""
        plan = []
        for s in local_scripts:
            plan.append(self._resolve(s))
        return plan

    def _resolve(self, script):
        # 绝对路径直接返回；相对路径拼到 root_dir
        if os.path.isabs(script):
            return script
        return os.path.join(self.root_dir, script)

    def _pick_bash(self):
        """探测 bash 可执行文件：优先系统 PATH 的 bash；Windows 下优先 Git for Windows（原生
        支持 Windows 路径），回退 WSL bash（需路径转换）。脚本内用 python3（Windows 无）时
        WSL bash 更稳，故 Windows 下优先 WSL。"""
        if os.name != "nt":
            return "bash"  # Linux/macOS 直接用 PATH bash
        # Windows：先看 PATH 里的 bash 是什么
        import shutil as _sh
        found = _sh.which("bash")
        if found and "system32" in found.lower():
            return found  # WSL bash
        # WSL bash（脚本内 python3 可用）
        wsl_bash = r"C:\Windows\System32\bash.exe"
        if os.path.exists(wsl_bash):
            return wsl_bash
        # Git for Windows
        git_bash = r"C:\Program Files\Git\bin\bash.exe"
        if os.path.exists(git_bash):
            return git_bash
        return found or "bash"

    # ---------- 执行 ----------
    def run_one(self, script):
        """执行单个脚本，返回 {script, exit_code, duration, output}。"""
        cmd = self._resolve(script)
        start = time.time()
        if self.dry_run:
            duration = time.time() - start
            return {"script": script, "exit_code": 0, "duration": round(duration, 3),
                    "output": "[dry-run] would run: %s" % script}
        try:
            bash = self._pick_bash()
            use_wsl = bash.lower().endswith("system32\\bash.exe")
            if use_wsl:
                # Windows + WSL bash：cd 到 /mnt/<盘>/... 再执行相对脚本
                proc = subprocess.run(
                    _wsl_popen_cmd(bash, script, self.root_dir),
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace",  # Windows 非 UTF-8 输出容错
                    timeout=self.timeout,
                    cwd=self.root_dir,
                )
            else:
                # Git for Windows 原生吃 Windows 路径；Linux 直接 bash
                proc = subprocess.run(
                    [bash, cmd],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace",  # Windows 非 UTF-8 输出容错
                    timeout=self.timeout,
                    cwd=self.root_dir,
                )
            duration = time.time() - start
            return {
                "script": script,
                "exit_code": proc.returncode,
                "duration": round(duration, 3),
                "output": (proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:],
            }
        except subprocess.TimeoutExpired:
            duration = time.time() - start
            return {"script": script, "exit_code": 124, "duration": round(duration, 3),
                    "output": "[timeout %ss]" % self.timeout}
        except Exception as e:  # noqa
            duration = time.time() - start
            return {"script": script, "exit_code": -1, "duration": round(duration, 3),
                    "output": "[error] %s" % e}

    def run(self, local_scripts):
        """批量执行，逐条记录，返回结果列表 + 汇总。"""
        results = [self.run_one(s) for s in local_scripts]
        ok = sum(1 for r in results if r["exit_code"] == 0)
        total_dur = round(sum(r["duration"] for r in results), 3)
        return {
            "results": results,
            "summary": {
                "total": len(results),
                "pass": ok,
                "fail": len(results) - ok,
                "total_duration": total_dur,
            },
        }

    # ---------- 一键链路 ----------
    def run_all(self, local_scripts):
        """判定已由外部完成，直接执行并返回 run() 结构。"""
        return self.run(local_scripts)


# 便捷单例
default_worker = LocalWorker()
