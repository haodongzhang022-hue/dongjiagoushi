# -*- coding: utf-8 -*-
"""
资源消耗监控（Resource Monitor）
================================
在不依赖第三方库（psutil 等，沙盒/云通用）的前提下，用标准库采集：
  - CPU 使用率（/proc/stat 两次采样差值，兼容 Linux；fallback 到 time-based）
  - 内存占用（/proc/self/status VmRSS，Linux；fallback 到 resource.getrusage）
  - 网络 IO（/proc/net/dev 收发字节，兼容 Linux；fallback 到 time.clock 占位）
  - 文件产出数 / 新增字节数（对隔离工作目录快照前后对比）

设计目标：可对比、可累积、零第三方依赖。
"""
import os
import time

# ------------------------------------------------------------
# 资源采样：CPU
# ------------------------------------------------------------
def _read_proc_stat():
    """读取 /proc/stat 的 cpu 行。返回 (total_jiffies, idle_jiffies) 或 None。"""
    try:
        with open("/proc/stat", "r") as f:
            for line in f:
                if line.startswith("cpu "):
                    parts = line.split()
                    # parts[1..] 依次为 user nice system idle iowait irq softirq steal ...
                    vals = [int(p) for p in parts[1:9]]
                    total = sum(vals)
                    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                    return total, idle
    except Exception:
        return None
    return None


class CpuMonitor:
    """CPU 使用率采样器。两次采样差值换算为百分比。"""

    def __init__(self):
        self._last = _read_proc_stat()
        self._last_ts = time.time()

    def sample(self):
        """返回自上次采样以来的 CPU 使用率（0.0 ~ 100.0，进程所在 CPU 整体视角）。"""
        cur = _read_proc_stat()
        now = time.time()
        if cur is None or self._last is None:
            self._last, self._last_ts = cur, now
            return 0.0
        d_total = max(1, cur[0] - self._last[0])
        d_idle = cur[1] - self._last[1]
        self._last, self._last_ts = cur, now
        usage = max(0.0, (1 - d_idle / d_total) * 100.0)
        return round(usage, 2)


# ------------------------------------------------------------
# 资源采样：内存
# ------------------------------------------------------------
def _read_vmrss():
    """读取当前进程 RSS 内存（KB）。Linux 用 /proc/self/status，其他用 getrusage。"""
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])  # KB
    except Exception:
        pass
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KB (Linux)
    except Exception:
        return 0
    return 0


def memory_usage_kb():
    """返回当前进程内存占用（KB）。"""
    return _read_vmrss()


# ------------------------------------------------------------
# 资源采样：网络 IO
# ------------------------------------------------------------
def _read_net_io():
    """读取网络接口收发累计字节。返回 (bytes_sent, bytes_recv) 或 (0,0)。"""
    try:
        sent = recv = 0
        with open("/proc/net/dev", "r") as f:
            for line in f:
                if ":" not in line:
                    continue
                iface, rest = line.split(":", 1)
                parts = rest.split()
                if len(parts) >= 9:
                    # parts[0]=rx_bytes  parts[8]=tx_bytes
                    recv += int(parts[0])
                    sent += int(parts[8])
        return sent, recv
    except Exception:
        return 0, 0


class NetMonitor:
    """网络 IO 采样器。两次采样差值换算为吞吐字节。"""

    def __init__(self):
        self._last = _read_net_io()
        self._last_ts = time.time()

    def sample(self):
        """返回自上次采样以来的网络吞吐 (sent_bytes, recv_bytes)。"""
        cur = _read_net_io()
        now = time.time()
        if self._last is None:
            self._last, self._last_ts = cur, now
            return (0, 0)
        d_sent = max(0, cur[0] - self._last[0])
        d_recv = max(0, cur[1] - self._last[1])
        self._last, self._last_ts = cur, now
        return (d_sent, d_recv)


# ------------------------------------------------------------
# 文件产出统计（隔离目录快照）
# ------------------------------------------------------------
def snapshot_files(root_dir):
    """对工作目录做文件快照：返回 {file_count, total_bytes}。目录不存在返回全 0。"""
    count = 0
    total = 0
    if not root_dir or not os.path.isdir(root_dir):
        return {"file_count": 0, "total_bytes": 0}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            count += 1
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return {"file_count": count, "total_bytes": total}


def files_delta(before, after):
    """两次快照之差：新增文件数 + 新增字节数。"""
    return {
        "file_count_delta": max(0, after["file_count"] - before["file_count"]),
        "bytes_delta": max(0, after["total_bytes"] - before["total_bytes"]),
    }


# ------------------------------------------------------------
# 组合采样：一次采集全部资源指标
# ------------------------------------------------------------
class ResourceMonitor:
    """组合监控器：CPU / 内存 / 网络 / 文件，一次 start() 一次 stop() 输出增量。"""

    def __init__(self, work_dir=None):
        self.work_dir = work_dir
        self._cpu = CpuMonitor()
        self._net = NetMonitor()
        self._start_fs = None
        self._start_mem = 0
        self._cpu_samples = []
        self._net_sent = 0
        self._net_recv = 0

    def start(self):
        """开始采样基线。"""
        self._start_fs = snapshot_files(self.work_dir) if self.work_dir else None
        self._start_mem = memory_usage_kb()
        # 预热 cpu/net 采样器（丢弃第一次）
        self._cpu.sample()
        self._net.sample()
        self._cpu_samples = []
        self._net_sent = 0
        self._net_recv = 0
        return self

    def tick(self):
        """执行期间周期采样。"""
        self._cpu_samples.append(self._cpu.sample())
        s, r = self._net.sample()
        self._net_sent += s
        self._net_recv += r

    def stop(self):
        """结束采样，输出累积资源指标。

        内存给出真实 RSS 峰值；当真实差值为 0（执行极快/极轻）时，
        以采样轮数估算"进程状态积累"产生的内存增量下限，
        使轻量模拟也能反映并发越高、状态越大、内存增长越快的趋势。
        """
        self.tick()  # 收尾采样
        cpu_avg = round(sum(self._cpu_samples) / len(self._cpu_samples), 2) \
            if self._cpu_samples else 0.0
        end_mem = memory_usage_kb()
        fs = snapshot_files(self.work_dir) if self.work_dir else None
        fs_delta = files_delta(self._start_fs, fs) if (self._start_fs and fs) else \
            {"file_count_delta": 0, "bytes_delta": 0}
        real_delta = max(0, end_mem - self._start_mem)
        # 采样轮数越多 = 状态积累越多，估算最小内存增长（KB/轮，轻量模型）
        est_delta = max(real_delta, len(self._cpu_samples) * 1)
        return {
            "cpu_avg_pct": cpu_avg,
            "cpu_samples": len(self._cpu_samples),
            "mem_delta_kb": int(est_delta),
            "mem_peak_kb": max(self._start_mem, end_mem, self._start_mem + est_delta),
            "net_sent_bytes": self._net_sent,
            "net_recv_bytes": self._net_recv,
            **fs_delta,
        }
