# -*- coding: utf-8 -*-
"""
驱动信息数据模型

定义驱动类别枚举和驱动信息数据类，作为整个应用的核心数据结构。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DriverCategory(Enum):
    """驱动类别枚举"""
    CHIPSET = "芯片组"
    MANAGEMENT_ENGINE = "Management Engine"
    VIDEO = "显卡"
    AUDIO = "声卡"
    NETWORK = "网卡"
    WIFI = "无线网卡"
    BLUETOOTH = "蓝牙"
    STORAGE = "存储控制器"
    TOUCHPAD = "触控板"
    USB = "USB 控制器"
    BIOS = "BIOS"
    FIRMWARE = "固件"
    PERIPHERAL = "外设"
    UNKNOWN = "未知"


# 驱动类别的安装优先级（数值越小越先安装）
CATEGORY_PRIORITY: dict[DriverCategory, int] = {
    DriverCategory.CHIPSET: 10,
    DriverCategory.MANAGEMENT_ENGINE: 20,
    DriverCategory.BIOS: 25,
    DriverCategory.FIRMWARE: 30,
    DriverCategory.STORAGE: 40,
    DriverCategory.VIDEO: 50,
    DriverCategory.AUDIO: 60,
    DriverCategory.NETWORK: 70,
    DriverCategory.WIFI: 75,
    DriverCategory.BLUETOOTH: 80,
    DriverCategory.USB: 85,
    DriverCategory.TOUCHPAD: 90,
    DriverCategory.PERIPHERAL: 100,
    DriverCategory.UNKNOWN: 999,
}


class InstallerType(Enum):
    """安装器类型枚举"""
    DELL_DUP = "Dell Update Package"
    INSTALLSHIELD = "InstallShield"
    NSIS = "NSIS"
    INNO_SETUP = "Inno Setup"
    MSI_WRAPPER = "MSI Wrapper"
    HP_SOFTPAQ = "HP SoftPaq"
    MSI = "MSI 驱动包"
    INF = "INF 驱动包"
    CAB = "CAB 驱动包"
    ZIP = "ZIP 驱动包"
    UNKNOWN = "未知"


# 各安装器类型对应的静默安装参数
INSTALLER_SILENT_ARGS: dict[InstallerType, list[str]] = {
    InstallerType.DELL_DUP: ["/s"],
    InstallerType.INSTALLSHIELD: ["/s", "/SMS"],
    InstallerType.NSIS: ["/S"],
    InstallerType.INNO_SETUP: ["/VERYSILENT", "/NORESTART"],
    InstallerType.MSI_WRAPPER: ["/quiet", "/norestart"],
    InstallerType.HP_SOFTPAQ: ["/s", "/e"],
    InstallerType.MSI: [],
    InstallerType.INF: [],
    InstallerType.CAB: [],
    InstallerType.ZIP: [],
    InstallerType.UNKNOWN: ["/s"],  # 回退默认值
}


class InstallStatus(Enum):
    """安装状态枚举"""
    PENDING = "pending"          # 等待安装
    INSTALLING = "installing"    # 正在安装
    SUCCESS = "success"          # 安装成功
    FAILED = "failed"            # 安装失败
    SKIPPED = "skipped"          # 用户跳过
    REBOOT_NEEDED = "reboot"     # 需要重启


@dataclass
class DriverInfo:
    """
    驱动信息数据类

    存储单个驱动文件的所有元信息，贯穿识别→排序→安装→日志的全流程。
    """
    # === 基本信息 ===
    name: str                                           # 驱动显示名称
    category: DriverCategory = DriverCategory.UNKNOWN   # 驱动类别
    vendor: str = ""                                    # 厂商名（Intel/Realtek/NVIDIA 等）
    file_path: str = ""                                 # 驱动安装包绝对路径
    file_size: int = 0                                  # 文件大小（字节）

    # === 识别信息 ===
    confidence: str = "low"         # 识别置信度："high" / "medium" / "low"
    installer_type: InstallerType = InstallerType.UNKNOWN  # 安装器类型
    silent_args: list[str] = field(default_factory=lambda: ["/s"])  # 静默安装参数

    # === PE 元数据 ===
    file_description: str = ""      # PE 版本信息中的 FileDescription
    product_name: str = ""          # PE 版本信息中的 ProductName
    company_name: str = ""          # PE 版本信息中的 CompanyName
    file_version: str = ""          # PE 版本信息中的 FileVersion
    signer: str = ""                # 数字签名者名称
    is_signed: bool = False         # 是否有有效的数字签名

    # === 安装状态 ===
    enabled: bool = True            # 用户是否勾选安装
    status: InstallStatus = InstallStatus.PENDING  # 当前安装状态
    error_message: str = ""         # 安装失败时的错误信息
    return_code: Optional[int] = None  # 安装进程返回码

    def get_priority(self) -> int:
        """获取安装优先级（用于排序）"""
        return CATEGORY_PRIORITY.get(self.category, 999)

    def to_dict(self) -> dict:
        """序列化为字典（用于会话保存）"""
        return {
            "name": self.name,
            "category": self.category.value,
            "vendor": self.vendor,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "confidence": self.confidence,
            "installer_type": self.installer_type.value,
            "silent_args": self.silent_args,
            "file_description": self.file_description,
            "product_name": self.product_name,
            "company_name": self.company_name,
            "file_version": self.file_version,
            "signer": self.signer,
            "is_signed": self.is_signed,
            "enabled": self.enabled,
            "status": self.status.value,
            "error_message": self.error_message,
            "return_code": self.return_code,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DriverInfo":
        """从字典反序列化（用于会话恢复）"""
        # 将字符串值转换回枚举
        category_map = {cat.value: cat for cat in DriverCategory}
        installer_map = {inst.value: inst for inst in InstallerType}
        status_map = {st.value: st for st in InstallStatus}

        return cls(
            name=data.get("name", ""),
            category=category_map.get(data.get("category", ""), DriverCategory.UNKNOWN),
            vendor=data.get("vendor", ""),
            file_path=data.get("file_path", ""),
            file_size=data.get("file_size", 0),
            confidence=data.get("confidence", "low"),
            installer_type=installer_map.get(data.get("installer_type", ""), InstallerType.UNKNOWN),
            silent_args=data.get("silent_args", ["/s"]),
            file_description=data.get("file_description", ""),
            product_name=data.get("product_name", ""),
            company_name=data.get("company_name", ""),
            file_version=data.get("file_version", ""),
            signer=data.get("signer", ""),
            is_signed=data.get("is_signed", False),
            enabled=data.get("enabled", True),
            status=status_map.get(data.get("status", ""), InstallStatus.PENDING),
            error_message=data.get("error_message", ""),
            return_code=data.get("return_code"),
        )

    def __str__(self) -> str:
        return f"[{self.category.value}] {self.name} ({self.vendor}) - 置信度: {self.confidence}"
