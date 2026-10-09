# -*- coding: utf-8 -*-
"""
设备信息数据模型

定义系统硬件设备的数据结构，用于硬件扫描结果的存储和展示。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DeviceStatus(Enum):
    """设备驱动状态枚举"""
    OK = "ok"                       # 驱动已正确安装
    GENERIC = "generic"             # 使用通用/基础驱动（可用但非最优）
    MISSING = "missing"             # 驱动缺失（设备无法正常工作）
    ERROR = "error"                 # 驱动存在错误
    UNKNOWN = "unknown"             # 无法判断状态


class IssueLevel(Enum):
    """问题严重程度（用于可视化分层）"""
    CRITICAL = "critical"           # 红色：缺失/故障
    WARNING = "warning"             # 黄色：性能受限/建议更新
    INFO = "info"                   # 灰色：运行正常
    SUCCESS = "success"             # 绿色：完美匹配


class MatchStatus(Enum):
    """与驱动文件夹的匹配状态"""
    NOT_CHECKED = "not_checked"     # 尚未进行匹配
    MATCHED = "matched"             # 在文件夹中找到匹配驱动
    NOT_MATCHED = "not_matched"     # 文件夹中未找到
    NOT_NEEDED = "not_needed"       # 不需要匹配（设备驱动正常）


# 设备类别与显示名称映射
DEVICE_CLASS_DISPLAY: dict[str, str] = {
    "Display": "显卡",
    "Net": "网卡",
    "Media": "声卡/多媒体",
    "AudioEndpoint": "音频端点",
    "HDC": "磁盘控制器",
    "SCSIAdapter": "存储控制器",
    "System": "系统设备",
    "USB": "USB 控制器",
    "HIDClass": "人机交互设备",
    "Bluetooth": "蓝牙",
    "Camera": "摄像头",
    "Biometric": "生物识别",
    "Mouse": "鼠标/触控板",
    "Keyboard": "键盘",
    "Monitor": "显示器",
    "PrintQueue": "打印机",
    "Firmware": "固件",
    "Processor": "处理器",
    "Battery": "电池",
    "Image": "图像设备",
    "WPD": "便携设备",
    "Software": "软件设备",
    "SecurityDevices": "安全设备",
}

# 关键设备类别（这些设备的驱动状态最重要）
CRITICAL_DEVICE_CLASSES = {
    "Display", "Net", "Media", "AudioEndpoint",
    "HDC", "SCSIAdapter", "Bluetooth", "Mouse",
}


@dataclass
class DeviceInfo:
    """
    系统硬件设备信息数据类

    存储通过 WMI 查询到的设备信息及其驱动状态分析结果。
    """
    # === 基本信息（WMI 获取） ===
    name: str = ""                      # 设备名称
    device_id: str = ""                 # 设备实例 ID（唯一标识）
    hardware_ids: list[str] = None      # 硬件 ID 列表（用于精确匹配）
    device_class: str = ""              # 设备类别（Display/Net/Media 等）
    manufacturer: str = ""              # 制造商
    driver_version: str = ""            # 当前驱动版本
    description: str = ""               # 设备描述

    # === 分析结果 ===
    status: DeviceStatus = DeviceStatus.UNKNOWN       # 驱动状态
    issue_level: IssueLevel = IssueLevel.INFO          # 问题优先级 (NEW)
    human_readable_status: str = ""                    # 用户友好描述 (NEW)
    is_filtered: bool = False                          # 是否被过滤（次要设备） (NEW)
    is_critical: bool = False                          # 是否为关键设备
    status_detail: str = ""                            # 状态详细说明

    # === 匹配结果 ===
    match_status: MatchStatus = MatchStatus.NOT_CHECKED   # 匹配状态
    matched_driver_name: str = ""                          # 匹配到的驱动文件名

    def __post_init__(self):
        if self.hardware_ids is None:
            self.hardware_ids = []
        self.is_critical = self.device_class in CRITICAL_DEVICE_CLASSES

    @property
    def class_display_name(self) -> str:
        """获取设备类别的中文显示名"""
        return DEVICE_CLASS_DISPLAY.get(self.device_class, self.device_class or "未知")

    @property
    def status_icon(self) -> str:
        """获取状态图标"""
        icons = {
            DeviceStatus.OK: "✅",
            DeviceStatus.GENERIC: "🔶",
            DeviceStatus.MISSING: "⚠️",
            DeviceStatus.ERROR: "❌",
            DeviceStatus.UNKNOWN: "❓",
        }
        return icons.get(self.status, "❓")

    @property
    def match_icon(self) -> str:
        """获取匹配状态图标"""
        icons = {
            MatchStatus.NOT_CHECKED: "—",
            MatchStatus.MATCHED: "📦",
            MatchStatus.NOT_MATCHED: "❓ 需下载",
            MatchStatus.NOT_NEEDED: "—",
        }
        return icons.get(self.match_status, "—")

    def __str__(self) -> str:
        return f"{self.status_icon} [{self.class_display_name}] {self.name} ({self.manufacturer})"
