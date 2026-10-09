# -*- coding: utf-8 -*-
"""
软件包信息数据模型

与 DriverInfo 平行，专门用于描述通用软件安装包（EXE/MSI/ZIP/Office）的元信息，
贯穿扫描 → 检测 → 安装 → 日志的全流程。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# 复用现有的安装状态枚举
from models.driver_info import InstallStatus


class PackageType(Enum):
    """安装包文件类型"""
    EXE = "EXE"
    MSI = "MSI"
    ZIP = "ZIP"
    OFFICE = "Office"  # Office 离线安装包（特殊处理）
    ISO = "ISO"        # 磁盘镜像（ISO/IMG）


class SoftwareInstallerType(Enum):
    """安装包打包工具类型（通过二进制特征检测）"""
    INNO_SETUP = "Inno Setup"
    NSIS = "NSIS"
    INSTALLSHIELD = "InstallShield"
    MSI = "MSI"
    OFFICE_ODT = "Office ODT"   # Office 部署工具（离线镜像）
    ZIP = "ZIP"
    ISO_IMAGE = "磁盘镜像"      # 需挂载后安装
    SFX_ARCHIVE = "自解压打包"   # 7-Zip / WinRAR / 7z SFX
    VMWARE = "VMware"           # VMware 专有安装器
    WISE = "Wise"               # Wise Installation
    PORTABLE_APP = "便携软件"    # 绿色软件，无需安装
    UNKNOWN = "未知"


# 各安装类型的静默安装参数
# 针对不同厂商和打包工具，选用最稳健的静默开关
SOFTWARE_SILENT_ARGS: dict[SoftwareInstallerType, list[str]] = {
    SoftwareInstallerType.INNO_SETUP:    ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
    SoftwareInstallerType.NSIS:          ["/S", "/v/qn"],  # 某些 NSIS 包装了 MSI，需要 /v/qn
    SoftwareInstallerType.INSTALLSHIELD: ["/s", "/v/qn", "REBOOT=ReallySuppress"],
    SoftwareInstallerType.MSI:           [],           # 由 msiexec 命令构建
    SoftwareInstallerType.OFFICE_ODT:    [],           # 由 setup.exe /configure 构建
    SoftwareInstallerType.ZIP:           [],           # 特殊处理：直接解压
    SoftwareInstallerType.SFX_ARCHIVE:   ["/S", "-y", "-gm2"],  # 兼顾 7z SFX (-y) 和 WinRAR SFX (-s)
    SoftwareInstallerType.VMWARE:        ["/s", "/v", "/qn", "REBOOT=ReallySuppress"],
    SoftwareInstallerType.WISE:          ["/s"],
    SoftwareInstallerType.PORTABLE_APP:  [],           # 绿色软件不执行静默安装
    SoftwareInstallerType.UNKNOWN:       ["/S"],       # 回退默认参数
}

# 各安装类型的超时时间（秒）
# Office 特殊延长至 3600 秒（1 小时），其余默认 300 秒
SOFTWARE_TIMEOUT: dict[SoftwareInstallerType, int] = {
    SoftwareInstallerType.OFFICE_ODT: 3600,
}
DEFAULT_INSTALL_TIMEOUT = 300  # 5 分钟默认超时

# ZIP 包默认解压根目录
ZIP_DEFAULT_EXTRACT_ROOT = "C:\\Tools"


# ── 签名核验状态常量 ──────────────────────────────────────────────────────
class SigStatus:
    UNCHECKED  = "UNCHECKED"   # 尚未核验
    VALID      = "VALID"       # 签名有效（可信机构签署）
    NOT_SIGNED = "NOT_SIGNED"  # 无数字签名
    TAMPERED   = "TAMPERED"    # 签名损坏或哈希不匹配（危险）
    ERROR      = "ERROR"       # 核验过程中出错（权限不足等）


@dataclass
class PackageInfo:
    """
    软件包信息数据类

    存储单个安装包的完整元信息，贯穿识别→安装→日志的全流程。
    """
    # === 基本信息 ===
    name: str                                                   # 显示名称（从文件名推导）
    file_path: str = ""                                         # 安装包绝对路径
    file_size: int = 0                                          # 文件大小（字节）

    # === 类型与参数 ===
    package_type: PackageType = PackageType.EXE                 # 文件类型
    installer_type: SoftwareInstallerType = SoftwareInstallerType.UNKNOWN  # 打包工具类型
    silent_args: list[str] = field(default_factory=list)        # 检测到的静默参数
    user_override_args: str = ""                                # 用户手动覆盖的参数（优先级最高）

    # === ZIP 包专属 ===
    zip_extract_path: str = ""                                  # 解压目标路径
    add_to_path: bool = False                                   # 是否加入系统 PATH
    zip_entrypoint: str = ""                                    # 解压后识别到的主程序路径
    create_shortcut: bool = False                               # 是否在解压后创建桌面快捷方式

    # === Office 包专属 ===
    office_config_path: str = ""                                # configuration.xml 路径

    # === ISO 镜像专属（运行时状态） ===
    temp_mount_drive: str = ""                                  # 自动挂载后的虚拟盘符（如 "F:"）

    # === 数字签名核验 ===
    sig_status: str = SigStatus.UNCHECKED                       # 签名状态（SigStatus 常量）
    sig_signer: str = ""                                        # 签名者名称（CN 字段）

    # === 安装状态 ===
    enabled: bool = True                                        # 用户是否勾选
    status: InstallStatus = InstallStatus.PENDING               # 当前安装状态
    error_message: str = ""                                     # 安装失败时的错误信息
    return_code: Optional[int] = None                           # 安装进程返回码

    def get_timeout(self) -> int:
        """获取该安装包的超时时间（秒）"""
        return SOFTWARE_TIMEOUT.get(self.installer_type, DEFAULT_INSTALL_TIMEOUT)

    def get_effective_args(self) -> list[str]:
        """
        获取最终生效的静默参数：
        - 如果用户有手动覆盖 → 使用用户参数
        - 否则使用检测到的静默参数
        """
        if self.user_override_args.strip():
            return self.user_override_args.strip().split()
        return self.silent_args

    def get_display_size(self) -> str:
        """格式化文件大小为人类可读字符串"""
        if self.file_size <= 0:
            return "–"
        elif self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 ** 2:
            return f"{self.file_size / 1024:.1f} KB"
        elif self.file_size < 1024 ** 3:
            return f"{self.file_size / 1024 ** 2:.1f} MB"
        else:
            return f"{self.file_size / 1024 ** 3:.2f} GB"

    def get_type_badge(self) -> str:
        """获取在 UI 标签中显示的类型文本"""
        if self.installer_type != SoftwareInstallerType.UNKNOWN:
            return self.installer_type.value
        return self.package_type.value

    def __str__(self) -> str:
        return f"[{self.package_type.value}|{self.installer_type.value}] {self.name} ({self.get_display_size()})"
