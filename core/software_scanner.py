# -*- coding: utf-8 -*-
"""
软件包文件夹扫描器

在异步线程中递归遍历目标文件夹，识别 EXE / MSI / ZIP 安装包，
对每个文件执行类型检测 + 数字签名核验，并通过信号通知 UI 层进度。
"""

import os
from PySide6.QtCore import QThread, Signal

from models.package_info import PackageInfo, PackageType, ZIP_DEFAULT_EXTRACT_ROOT, SigStatus
from core.software_detector import SoftwareDetector
from core.signature_checker import batch_check_signatures
from utils.logger import get_logger

logger = get_logger("SoftwareScanner")

# 支持的安装包扩展名
_SUPPORTED_EXTENSIONS = {".exe", ".msi", ".zip", ".iso", ".img"}

# 过滤规则：文件名包含以下关键词时跳过（反安装程序等噪音文件）
_FILTER_NAME_KEYWORDS = [
    "unins", "uninstall", "uninst", "remove",
    "helper", "_helper", 
    "crash", "repair", "setup_helper",
]

# 过滤规则：仅当文件小于此大小（字节）时才检查名称关键词
_SMALL_FILE_THRESHOLD = 5 * 1024 * 1024  # 5 MB 以下才做关键词过滤


class SoftwareScanWorker(QThread):
    """
    软件包扫描线程

    信号：
      scan_progress(current, total)     → 通知 UI 更新进度
      scan_finished(list[PackageInfo])  → 返回完整的扫描结果列表
      scan_error(str)                   → 扫描出错时发出错误信息
    """

    scan_progress = Signal(int, int)         # (当前, 总数)
    scan_finished = Signal(list)             # List[PackageInfo]
    scan_error = Signal(str)                 # 错误消息

    def __init__(self, folder: str, recursive: bool = True, parent=None):
        super().__init__(parent)
        self._folder = folder
        self._recursive = recursive
        self._cancelled = False

    def cancel(self):
        """取消扫描"""
        self._cancelled = True

    def run(self):
        """线程主体：遍历文件夹 → 过滤 → 检测 → 签名核验 → 发射结果"""
        logger.info(f"=== 开始软件包扫描: {self._folder} (递归={self._recursive}) ===")

        try:
            # 第一步：收集所有候选文件路径
            candidates = self._collect_files()
            total = len(candidates)
            logger.info(f"  共扫描到 {total} 个候选文件")

            if total == 0:
                self.scan_finished.emit([])
                return

            # 第一步.附：批量进行数字签名核验
            self.scan_progress.emit(0, total)
            logger.info("  正在进行批量数字签名解析...")
            self._sig_cache = batch_check_signatures(candidates)

            # 第二步：获取基础信息 + 并入签名结果
            packages: list[PackageInfo] = []
            for i, file_path in enumerate(candidates):
                if self._cancelled:
                    logger.info("  扫描被用户取消")
                    break

                self.scan_progress.emit(i + 1, total)
                pkg = self._build_package_info(file_path)
                if pkg:
                    packages.append(pkg)
                    sig_label = {
                        SigStatus.VALID:      "🔐 有效签名",
                        SigStatus.NOT_SIGNED: "⚠️ 无签名",
                        SigStatus.TAMPERED:   "❌ 签名异常",
                        SigStatus.ERROR:      "? 核验失败",
                    }.get(pkg.sig_status, "")
                    logger.info(f"  [{i+1}/{total}] {pkg} | {sig_label}")

            logger.info(f"=== 扫描完成: {len(packages)} 个有效安装包 ===")
            self.scan_finished.emit(packages)

        except Exception as e:
            msg = f"扫描异常: {str(e)}"
            logger.error(msg)
            self.scan_error.emit(msg)

    def _collect_files(self) -> list[str]:
        """递归（或单层）收集支持扩展名的文件路径列表"""
        result = []

        if self._recursive:
            for root, dirs, files in os.walk(self._folder):
                # 跳过隐藏目录
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in _SUPPORTED_EXTENSIONS:
                        result.append(os.path.join(root, fname))
        else:
            for fname in os.listdir(self._folder):
                ext = os.path.splitext(fname)[1].lower()
                if ext in _SUPPORTED_EXTENSIONS:
                    result.append(os.path.join(self._folder, fname))

        return result

    def _build_package_info(self, file_path: str) -> PackageInfo | None:
        """为单个文件构建 PackageInfo 并执行类型检测 + 签名核验"""
        file_name = os.path.basename(file_path)
        name_lower = file_name.lower()
        ext = os.path.splitext(file_name)[1].lower()

        # 过滤噪音文件（反安装程序、辅助工具等）
        try:
            size = os.path.getsize(file_path)
        except OSError:
            return None

        if size < _SMALL_FILE_THRESHOLD:
            for kw in _FILTER_NAME_KEYWORDS:
                if kw in name_lower:
                    logger.debug(f"    过滤 (噪音): {file_name}")
                    return None

        # 确定 PackageType
        if ext == ".zip":
            pkg_type = PackageType.ZIP
        elif ext == ".msi":
            pkg_type = PackageType.MSI
        elif ext in {".iso", ".img"}:
            pkg_type = PackageType.ISO
        else:
            pkg_type = PackageType.EXE

        # 构建原始名称（去掉扩展名）
        display_name = os.path.splitext(file_name)[0]

        # 构建 PackageInfo
        pkg = PackageInfo(
            name=display_name,
            file_path=file_path,
            file_size=size,
            package_type=pkg_type,
        )

        # ZIP 包设置默认解压路径
        if pkg_type == PackageType.ZIP:
            pkg.zip_extract_path = os.path.join(ZIP_DEFAULT_EXTRACT_ROOT, display_name)

        # 执行类型检测（含 Office 识别）
        pkg = SoftwareDetector.detect(pkg)

        # Office 包：查找 configuration.xml
        from models.package_info import SoftwareInstallerType
        if pkg.installer_type == SoftwareInstallerType.OFFICE_ODT:
            config = SoftwareDetector.find_office_config(file_path)
            if config:
                pkg.office_config_path = config
                logger.info(f"    Office 配置文件: {config}")

        # 从批量扫描缓存中提取数字签名（ZIP 包无缝忽略）
        if pkg_type != PackageType.ZIP:
            sig_status, sig_signer = self._sig_cache.get(file_path, (SigStatus.UNCHECKED, ""))
            pkg.sig_status = sig_status
            pkg.sig_signer = sig_signer
        else:
            pkg.sig_status = SigStatus.NOT_SIGNED  # ZIP 文件直接跳过危险告警

        return pkg
