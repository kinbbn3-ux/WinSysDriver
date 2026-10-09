# -*- coding: utf-8 -*-
"""
安装包类型检测器

通过二进制特征字符串扫描识别 EXE 安装包的打包工具类型，
并返回对应的推荐静默安装参数。支持 Office 目录结构检测。
"""

import os
from models.package_info import (
    PackageType, SoftwareInstallerType, SOFTWARE_SILENT_ARGS, PackageInfo
)
from utils.logger import get_logger

logger = get_logger("SoftwareDetector")

# ── 二进制特征检测矩阵 ────────────────────────────────────────────────────
# 格式：(特征字节串列表, 对应的 SoftwareInstallerType)
# 按优先级从高到低排列（先匹配先返回）
_BINARY_SIGNATURES: list[tuple[list[bytes], SoftwareInstallerType]] = [
    # Inno Setup — 高置信度特征（版本无关）
    (
        [b"Inno Setup Setup Data", b"JR.Inno", b"Inno Setup Messages"],
        SoftwareInstallerType.INNO_SETUP
    ),
    # NSIS — Nullsoft Scriptable Install System
    (
        [b"Nullsoft.NSIS.exehead", b"NSIS Error", b"NullsoftInst"],
        SoftwareInstallerType.NSIS
    ),
    # VMware 专有引导器
    (
        [b"VMware Installer", b"VMware-workstation", b"VMware-player"],
        SoftwareInstallerType.VMWARE
    ),
    # InstallShield
    (
        [b"InstallShield", b"IS Setup"],
        SoftwareInstallerType.INSTALLSHIELD
    ),
    # Wise Installation
    (
        [b"Wise Installation System", b"Wise InstallationWizard", b"WISEINST"],
        SoftwareInstallerType.WISE
    ),
    # 自解压类安装包 (7-Zip / WinRAR / 7z SFX)
    (
        [b"7z Setup SFX", b"7-Zip", b"Rar!", b"7z.SFX"],
        SoftwareInstallerType.SFX_ARCHIVE
    ),
]

# 扫描的二进制片段大小（前 512KB，足以覆盖所有已知签名位置）
_SCAN_BYTES = 512 * 1024

# Office 目录结构特征（离线安装包）
_OFFICE_SETUP_FILES = ["setup.exe"]
_OFFICE_SUBFOLDER_HINTS = ["Office16", "Office15", "Office19", "Office21", "Office"]


class SoftwareDetector:
    """
    安装包类型检测器

    支持：
    1. EXE 二进制特征扫描（Inno / NSIS / InstallShield）
    2. MSI 文件扩展名识别
    3. ZIP 文件扩展名识别
    4. Office 离线安装包目录结构识别
    """

    @classmethod
    def detect(cls, pkg: PackageInfo) -> PackageInfo:
        """
        对单个 PackageInfo 执行完整检测，原地修改并返回。

        Args:
            pkg: 待检测的软件包信息（需要 file_path 已设置）

        Returns:
            已填充 installer_type 和 silent_args 的 PackageInfo
        """
        ext = os.path.splitext(pkg.file_path)[1].lower()

        # ZIP 包：无需检测，直接返回
        if ext == ".zip" or pkg.package_type == PackageType.ZIP:
            pkg.installer_type = SoftwareInstallerType.ZIP
            pkg.silent_args = []
            return pkg

        # MSI 包：扩展名即可确定
        if ext == ".msi" or pkg.package_type == PackageType.MSI:
            pkg.installer_type = SoftwareInstallerType.MSI
            pkg.silent_args = []  # 由 installer 构建 msiexec 命令
            return pkg

        # ISO 镜像包：标记为待挂载安装
        if ext in {".iso", ".img"} or pkg.package_type == PackageType.ISO:
            pkg.installer_type = SoftwareInstallerType.ISO_IMAGE
            pkg.package_type = PackageType.ISO
            pkg.silent_args = []
            logger.info(f"  [ISO] 检测到磁盘镜像: {pkg.name}")
            return pkg

        # Office 包：目录结构检测（当 file_path 指向 setup.exe）
        if cls._is_office_installer(pkg.file_path):
            pkg.installer_type = SoftwareInstallerType.OFFICE_ODT
            pkg.package_type = PackageType.OFFICE
            pkg.silent_args = []  # 由 installer 构建 /configure 命令
            logger.info(f"  [Office] 检测到 Office 离线安装包: {pkg.name}")
            return pkg

        # EXE 包：结合特征与启发式规则检测
        if ext == ".exe":
            detected = cls._scan_binary(pkg.file_path)
            
            # 若二进制无法识别，则通过启发式方法判断是否为“绿色便携软件”
            if detected == SoftwareInstallerType.UNKNOWN:
                if cls._is_likely_portable(pkg.file_path):
                    detected = SoftwareInstallerType.PORTABLE_APP
            
            pkg.installer_type = detected
            pkg.silent_args = SOFTWARE_SILENT_ARGS.get(detected, ["/S"])
            logger.debug(f"  [检测] {pkg.name} → {detected.value} | 参数: {pkg.silent_args}")

        return pkg

    @classmethod
    def _scan_binary(cls, file_path: str) -> SoftwareInstallerType:
        """
        读取文件前 512KB 执行二进制特征扫描。

        读取前即进行大小检查，避免对 1B 文件做无意义的读取。
        """
        try:
            file_size = os.path.getsize(file_path)
            if file_size < 1024:
                return SoftwareInstallerType.UNKNOWN

            with open(file_path, "rb") as f:
                data = f.read(min(_SCAN_BYTES, file_size))

            for signatures, installer_type in _BINARY_SIGNATURES:
                for sig in signatures:
                    if sig in data:
                        return installer_type

        except (OSError, PermissionError) as e:
            logger.warning(f"    无法读取文件 {file_path}: {e}")

        return SoftwareInstallerType.UNKNOWN

    @classmethod
    def _is_office_installer(cls, exe_path: str) -> bool:
        """
        检测 EXE 是否为 Office 离线安装包的 setup.exe。

        条件：
        - 文件名为 setup.exe（不区分大小写）
        - 同级目录或父目录下存在 Office 相关子文件夹
        """
        base_name = os.path.basename(exe_path).lower()
        if base_name != "setup.exe":
            return False

        # 检查同级目录下是否有 Office 子文件夹特征
        parent_dir = os.path.dirname(exe_path)
        try:
            entries = os.listdir(parent_dir)
            for subfolder in _OFFICE_SUBFOLDER_HINTS:
                if subfolder.lower() in [e.lower() for e in entries]:
                    return True

            # 检查是否存在 configuration.xml（Office ODT 的标志）
            config_xml = os.path.join(parent_dir, "configuration.xml")
            if os.path.isfile(config_xml):
                return True

        except OSError:
            pass

        return False

    @classmethod
    def find_office_config(cls, setup_exe_path: str) -> str:
        """
        在 Office setup.exe 同级目录查找 configuration.xml。
        如果不存在，返回空字符串。
        """
        parent_dir = os.path.dirname(setup_exe_path)
        config_path = os.path.join(parent_dir, "configuration.xml")
        return config_path if os.path.isfile(config_path) else ""

    @classmethod
    def _is_likely_portable(cls, file_path: str) -> bool:
        """
        启发式判断是否为绿色软件：
        1. 文件名中不含 setup / install / update / patch / download 等关键词
        2. 读取 PE 元数据检查文件描述
        3. 文件大小相对较小
        """
        name = os.path.basename(file_path).lower()
        installer_keywords = ["setup", "install", "update", "patch", "upgrade", "deploy", "downloader"]
        
        # 1. 检查文件名
        if any(kw in name for kw in installer_keywords):
            return False
            
        # 2. 检查 PE 元数据（若提取成功）
        try:
            from utils.pe_reader import read_version_info
            pe_info = read_version_info(file_path)
            desc = pe_info.get("FileDescription", "").lower()
            if any(kw in desc for kw in installer_keywords):
                return False
        except Exception:
            pass
            
        # 3. 检查大小（放宽到 30MB 内均有可能，配合前面严格的规则）
        try:
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if size_mb < 30: 
                return True
        except OSError:
            pass
            
        return False
