# -*- coding: utf-8 -*-
"""
实时硬件监控引擎 (Monitoring Engine)

职责分离：
 - MonitoringEngine  : 纯数据采集静态工具类（无 Qt 依赖，可随时在子线程调用）
 - MonitorWorker     : QThread 工作线程，定期采集数据然后通过 Signal 推送给 UI
 - MonitorController : 对外暴露的控制器，供 DashboardWidget 直接使用
"""

import subprocess
import platform
import psutil
from typing import Dict, Any, List

from PySide6.QtCore import QThread, Signal, QTimer
from utils.logger import get_logger

logger = get_logger("MonitoringEngine")


# ─────────────────────────────────────────────────────────────
#  纯数据采集层（不含任何 Qt 对象，可以在任意线程调用）
# ─────────────────────────────────────────────────────────────
class MonitoringEngine:
    """硬件数据采集工具类 — 所有方法均为纯函数，无状态"""

    # ── PowerShell 复用：将多条查询合并为单次调用 ────────────
    _PS_BATCH = r"""
$result = @{}

# CPU 温度（WMI ThermalZone，需管理员权限）
try {
    $temps = (Get-CimInstance -Namespace root/wmi -ClassName MsAcpi_ThermalZoneTemperature -ErrorAction Stop).CurrentTemperature
    $maxC = ($temps | Measure-Object -Maximum).Maximum / 10.0 - 273.15
    $result['cpu_temp'] = [int]$maxC
} catch { $result['cpu_temp'] = -1 }

# GPU 核心负载（Win10/11 性能计数器）
try {
    $util = (Get-CimInstance -Namespace root/cimv2 -ClassName Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction Stop |
             Measure-Object -Property UtilizationPercentage -Sum).Sum
    $result['gpu_util'] = [int]$util
} catch { $result['gpu_util'] = -1 }

# 风扇转速 (尝试多种常见 WMI 路径)
try {
    $f = Get-CimInstance -ClassName Win32_Fan -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($f) {
        $rpm = if ($f.CurrentReading) { $f.CurrentReading } else { $f.DesiredSpeed }
        $result['fan_rpm'] = if ($rpm) { [int]$rpm } else { -1 }
    } else {
        # 尝试一些品牌特定的 WMI (如某些主板会暴露在其他地方)
        $result['fan_rpm'] = -1
    }
} catch { $result['fan_rpm'] = -1 }

$result | ConvertTo-Json -Compress
"""

    @staticmethod
    def collect_realtime() -> Dict[str, Any]:
        """
        一次性采集所有实时指标（CPU/RAM/GPU/风扇）。
        只启动 **一个** PowerShell 进程完成所有 WMI 查询，
        理论延迟从「查询数×延迟」降为「max(各查询延迟)」。
        """
        data: Dict[str, Any] = {}

        # 1. psutil 系列（纯 Python，几乎不阻塞）
        data["cpu_percent"] = psutil.cpu_percent(interval=None)
        freq = psutil.cpu_freq()
        data["cpu_clock"] = f"{freq.current / 1000:.1f} GHz" if freq else "–"

        mem = psutil.virtual_memory()
        data["ram_used_gb"]  = mem.used  / (1024 ** 3)
        data["ram_total_gb"] = mem.total / (1024 ** 3)
        data["ram_percent"]  = mem.percent

        data["process_count"] = len(psutil.pids())

        # 2. 单次 PowerShell 批量查询
        ps_result = MonitoringEngine._run_ps_batch()
        cpu_temp = ps_result.get("cpu_temp", -1)
        data["cpu_temp"] = f"{cpu_temp}°C" if cpu_temp >= 0 else "–"

        gpu_util = ps_result.get("gpu_util", -1)
        data["gpu_util"] = gpu_util if gpu_util >= 0 else 0
        data["gpu_util_ok"] = gpu_util >= 0     # 是否拿到了真实值

        fan_rpm = ps_result.get("fan_rpm", -1)
        data["fan_rpm"] = f"{fan_rpm} RPM" if fan_rpm > 0 else "– RPM"

        return data

    @staticmethod
    def _run_ps_batch() -> Dict[str, Any]:
        """执行批量 PowerShell 查询，超时后返回空字典 (不阻塞调用方)"""
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 MonitoringEngine._PS_BATCH],
                capture_output=True, text=True,
                timeout=3,                            # 硬超时：3 秒
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if res.stdout.strip():
                import json
                return json.loads(res.stdout.strip())
        except Exception as e:
            logger.debug(f"PS 批量查询异常: {e}")
        return {}

    @staticmethod
    def get_static_info() -> Dict[str, Any]:
        """获取静态硬件信息（型号/总容量），只需在启动时调用一次"""
        cpu_model = platform.processor() or "Unknown CPU"
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            cpu_model, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        except Exception:
            pass

        mem   = psutil.virtual_memory()
        total_ram = round(mem.total / (1024 ** 3))

        gpu_model = "Generic Graphics"
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if res.stdout.strip():
                gpu_model = res.stdout.strip().split("\n")[0]
        except Exception:
            pass

        disks: List[Dict] = []
        for part in psutil.disk_partitions(all=False):
            if "fixed" in part.opts or part.fstype:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        "device":  part.device,
                        "mount":   part.mountpoint,
                        "total":   usage.total,
                        "free":    usage.free,
                        "percent": usage.percent,
                    })
                except Exception:
                    continue

        return {
            "cpu_model":    cpu_model.strip(),
            "total_ram_gb": total_ram,
            "gpu_model":    gpu_model.strip(),
            "disks":        disks,
        }


# ─────────────────────────────────────────────────────────────
#  后台工作线程（只负责数据采集，绝不操作任何 Qt Widget）
# ─────────────────────────────────────────────────────────────
class MonitorWorker(QThread):
    """
    独立后台线程，每隔 interval_ms 采集一次实时数据，
    采集完毕后通过 Signal 把结果推送到主线程。

    设计要点：
    - 线程内部使用「采集 + sleep」循环，避免 QTimer 跨线程问题
    - _running 标志位实现安全停止，无需 terminate()
    - 采集期间主线程完全不阻塞
    """
    # 携带完整实时快照的信号
    data_ready = Signal(dict)

    def __init__(self, interval_ms: int = 4000, parent=None):
        super().__init__(parent)
        self._interval_ms = interval_ms
        self._running = False

    def run(self):
        self._running = True
        logger.info("监控后台线程启动")
        while self._running:
            try:
                snapshot = MonitoringEngine.collect_realtime()
                if self._running:               # 采集期间可能已经停止
                    self.data_ready.emit(snapshot)
            except Exception as e:
                logger.debug(f"监控采集异常: {e}")
            # 分段 sleep，让停止请求能快速响应
            elapsed = 0
            while self._running and elapsed < self._interval_ms:
                self.msleep(100)
                elapsed += 100
        logger.info("监控后台线程退出")

    def stop(self):
        """请求停止，最多等待采集超时+100ms 后退出"""
        self._running = False
        self.wait(self._interval_ms + 500)
