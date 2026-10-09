# -*- coding: utf-8 -*-
"""
驱动识别引擎

通过三层递进策略识别驱动 exe 文件的类别：
1. 文件名关键词匹配
2. PE 文件元数据分析
3. 数字签名验证

识别结果包括驱动类别、厂商、安装器类型和静默安装参数。
"""

import os
import re
import hashlib
from typing import Optional

from models.driver_info import (
    DriverCategory, DriverInfo, InstallerType,
    INSTALLER_SILENT_ARGS
)
from utils.pe_reader import read_version_info
from utils.logger import get_logger
from core.driver_package import read_inf_metadata, verify_driver_package

logger = get_logger("DriverAnalyzer")

_SUPPORTED_DRIVER_EXTENSIONS = {".exe", ".msi", ".inf", ".cab", ".zip"}


# ============================================================
# 文件名关键词 → 驱动类别映射表
# 使用正则表达式匹配（不区分大小写）
# ============================================================
_FILENAME_CATEGORY_RULES: list[tuple[str, DriverCategory]] = [
    # 芯片组
    (r"(?i)chipset", DriverCategory.CHIPSET),
    (r"(?i)intel.*serial.*io", DriverCategory.CHIPSET),
    (r"(?i)intel.*hid", DriverCategory.CHIPSET),
    (r"(?i)platform.*dynamic.*framework", DriverCategory.CHIPSET),

    # Management Engine
    (r"(?i)management.?engine|intel.?me(?:i)?", DriverCategory.MANAGEMENT_ENGINE),
    (r"(?i)thunderbolt", DriverCategory.MANAGEMENT_ENGINE),

    # 显卡
    (r"(?i)video|graphics|vga|display|gpu", DriverCategory.VIDEO),
    (r"(?i)nvidia|geforce|radeon|intel.?(?:uhd|iris|hd).?graphics", DriverCategory.VIDEO),

    # 声卡
    (r"(?i)audio|sound|realtek.*audio|waves.*maxx", DriverCategory.AUDIO),

    # 有线网卡
    (r"(?i)(?<!wi)(?:network|ethernet|lan|nic)(?!.*wi)", DriverCategory.NETWORK),
    (r"(?i)realtek.*ethernet|intel.*ethernet", DriverCategory.NETWORK),

    # 无线网卡
    (r"(?i)wi-?fi|wifi|wlan|wireless(?!.*blue)", DriverCategory.WIFI),
    (r"(?i)intel.*wireless|killer.*wireless|qualcomm.*wireless", DriverCategory.WIFI),

    # 蓝牙
    (r"(?i)bluetooth|blue-?tooth|bt\d", DriverCategory.BLUETOOTH),

    # 存储控制器
    (r"(?i)storage|ahci|nvme|raid|rst|rapid", DriverCategory.STORAGE),
    (r"(?i)intel.*rapid|samsung.*nvme|phison", DriverCategory.STORAGE),

    # 触控板
    (r"(?i)touchpad|touch-?pad|synaptics|elan.?touch|alps", DriverCategory.TOUCHPAD),
    (r"(?i)precision.*touch|i2c.*hid", DriverCategory.TOUCHPAD),

    # USB 控制器
    (r"(?i)usb.*(?:controller|driver|host)", DriverCategory.USB),

    # BIOS / 固件
    (r"(?i)bios(?!.*guard)", DriverCategory.BIOS),
    (r"(?i)firmware|fw.?update", DriverCategory.FIRMWARE),
]


# ============================================================
# 厂商名关键词 → 驱动类别映射表（用于 PE 元数据分析）
# ============================================================
_VENDOR_CATEGORY_HINTS: dict[str, DriverCategory] = {
    "nvidia": DriverCategory.VIDEO,
    "amd": DriverCategory.VIDEO,
    "realtek semiconductor": DriverCategory.AUDIO,
    "intel corporation": DriverCategory.CHIPSET,  # 作为默认值，会被更精确的匹配覆盖
}


# ============================================================
# 安装器类型检测规则（基于 PE 元数据）
# ============================================================
_INSTALLER_DETECTION_RULES: list[tuple[str, str, InstallerType]] = [
    # (字段名, 关键词正则, 安装器类型)
    ("CompanyName", r"(?i)dell", InstallerType.DELL_DUP),
    ("LegalCopyright", r"(?i)nullsoft", InstallerType.NSIS),
    ("CompanyName", r"(?i)nullsoft", InstallerType.NSIS),
    ("LegalCopyright", r"(?i)jordan\s*russell", InstallerType.INNO_SETUP),
    ("FileDescription", r"(?i)inno\s*setup", InstallerType.INNO_SETUP),
    ("ProductName", r"(?i)installshield", InstallerType.INSTALLSHIELD),
    ("CompanyName", r"(?i)flexera|macrovision|installshield", InstallerType.INSTALLSHIELD),
    ("CompanyName", r"(?i)hewlett.?packard|hp\s+inc", InstallerType.HP_SOFTPAQ),
    ("OriginalFilename", r"(?i)\.msi$", InstallerType.MSI_WRAPPER),
]


def scan_folder(folder_path: str) -> list[DriverInfo]:
    """
    扫描文件夹中的所有 exe 文件，识别驱动信息

    Args:
        folder_path: 文件夹绝对路径

    Returns:
        识别到的 DriverInfo 列表
    """
    if not os.path.isdir(folder_path):
        logger.error(f"文件夹不存在: {folder_path}")
        return []

    drivers: list[DriverInfo] = []
    seen_content: dict[tuple[int, str], str] = {}

    # 遍历文件夹（包含子文件夹）
    for root, _dirs, files in os.walk(folder_path):
        for filename in files:
            if os.path.splitext(filename)[1].lower() not in _SUPPORTED_DRIVER_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            logger.info(f"正在分析: {filename}")

            duplicate_of = _find_duplicate(file_path, seen_content)
            if duplicate_of:
                logger.info(f"  → 跳过重复文件: {filename}（与 {duplicate_of} 内容相同）")
                continue

            try:
                driver = _analyze_single_file(file_path, filename)
                file_key = _content_key(file_path)
                if file_key:
                    seen_content[file_key] = filename
                drivers.append(driver)
                logger.info(f"  → {driver}")
            except Exception as e:
                logger.error(f"分析文件异常 [{filename}]: {e}")
                # 即使分析失败，也创建一个最基本的驱动信息
                drivers.append(DriverInfo(
                    name=filename,
                    file_path=file_path,
                    file_size=os.path.getsize(file_path),
                    confidence="low",
                ))

    logger.info(f"扫描完成，共识别到 {len(drivers)} 个驱动文件")
    return drivers


def _analyze_single_file(file_path: str, filename: str) -> DriverInfo:
    """
    分析单个驱动安装包，返回驱动信息

    执行文件名、PE 元数据和数字签名识别

    Args:
        file_path: 文件绝对路径
        filename: 文件名

    Returns:
        识别结果 DriverInfo
    """
    driver = DriverInfo(
        name=filename,
        file_path=file_path,
        file_size=os.path.getsize(file_path),
    )

    extension = os.path.splitext(filename)[1].lower()
    package_types = {
        ".msi": InstallerType.MSI,
        ".inf": InstallerType.INF,
        ".cab": InstallerType.CAB,
        ".zip": InstallerType.ZIP,
    }
    if extension in package_types:
        driver.installer_type = package_types[extension]
        driver.silent_args = []

    # === 第一层：文件名关键词匹配 ===
    category_from_name, confidence_name = _match_by_filename(filename)
    if category_from_name != DriverCategory.UNKNOWN:
        driver.category = category_from_name
        driver.confidence = confidence_name

    # === 第二层：PE 元数据分析 ===
    version_info = read_version_info(file_path) if extension == ".exe" else {}
    if version_info:
        driver.file_description = version_info.get("FileDescription", "")
        driver.product_name = version_info.get("ProductName", "")
        driver.company_name = version_info.get("CompanyName", "")
        driver.file_version = version_info.get("FileVersion", "")

        # 尝试用元数据改善识别结果
        category_from_meta, vendor, confidence_meta = _match_by_metadata(version_info)

        # 如果元数据给出了更精确的分类
        if category_from_meta != DriverCategory.UNKNOWN:
            if driver.category == DriverCategory.UNKNOWN:
                driver.category = category_from_meta
                driver.confidence = confidence_meta
            elif driver.category == category_from_meta:
                # 文件名和元数据一致，提升置信度
                driver.confidence = "high"

        if vendor:
            driver.vendor = vendor

        # 从元数据生成更友好的显示名称
        display_name = _generate_display_name(version_info, filename)
        if display_name:
            driver.name = display_name

        # 检测安装器类型
        installer_type = _detect_installer_type(version_info)
        if extension == ".exe":
            driver.installer_type = installer_type
            driver.silent_args = list(INSTALLER_SILENT_ARGS.get(
                installer_type, INSTALLER_SILENT_ARGS[InstallerType.UNKNOWN]
            ))

    if extension in {".inf", ".cab", ".zip"}:
        inf_metadata = read_inf_metadata(file_path, driver.installer_type)
        driver.vendor = inf_metadata.get("provider", "")
        driver.file_version = inf_metadata.get("driver_version", "")
        category_from_inf = _match_by_inf_metadata(inf_metadata, filename)
        if category_from_inf != DriverCategory.UNKNOWN:
            driver.category = category_from_inf
            driver.confidence = "medium"

    # === 第三层：数字签名验证 ===
    is_signed, signer = verify_driver_package(file_path, driver.installer_type)
    driver.is_signed = is_signed
    driver.signer = signer

    if signer:
        # 尝试从签名者推断类别
        category_from_signer = _match_by_signer(signer)
        if category_from_signer != DriverCategory.UNKNOWN:
            if driver.category == DriverCategory.UNKNOWN:
                driver.category = category_from_signer
                driver.confidence = "medium"
            elif driver.category == category_from_signer:
                driver.confidence = "high"

        # 从签名者提取厂商信息
        if not driver.vendor:
            driver.vendor = _extract_vendor_from_signer(signer)

    if driver.category in {DriverCategory.BIOS, DriverCategory.FIRMWARE}:
        driver.enabled = False
        logger.warning(f"  → BIOS/固件包默认不勾选，需人工确认: {driver.name}")

    # 最终兜底：确保有基本的静默参数
    if not driver.silent_args:
        driver.silent_args = ["/s"]

    return driver


def _find_duplicate(
    file_path: str, seen_content: dict[tuple[int, str], str]
) -> str:
    try:
        key = _content_key(file_path)
    except OSError:
        return ""
    return seen_content.get(key, "") if key else ""


def _content_key(file_path: str) -> tuple[int, str] | None:
    try:
        file_size = os.path.getsize(file_path)
        digest = hashlib.sha256()
        with open(file_path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return file_size, digest.hexdigest()
    except OSError:
        return None


def _match_by_inf_metadata(
    metadata: dict[str, str], filename: str
) -> DriverCategory:
    all_text = " ".join(
        (metadata.get("class", ""), metadata.get("provider", ""), filename)
    )
    class_rules = (
        (r"(?i)display", DriverCategory.VIDEO),
        (r"(?i)media", DriverCategory.AUDIO),
        (r"(?i)^\s*net\s*$", DriverCategory.NETWORK),
        (r"(?i)bluetooth", DriverCategory.BLUETOOTH),
        (r"(?i)hdc|scsiadapter|s?ata", DriverCategory.STORAGE),
        (r"(?i)usb", DriverCategory.USB),
        (r"(?i)system", DriverCategory.CHIPSET),
        (r"(?i)firmware", DriverCategory.FIRMWARE),
    )
    class_name = metadata.get("class", "")
    for pattern, category in class_rules:
        if re.search(pattern, class_name):
            return category
    for pattern, category in _FILENAME_CATEGORY_RULES:
        if re.search(pattern, all_text):
            return category
    return DriverCategory.UNKNOWN


def _match_by_filename(filename: str) -> tuple[DriverCategory, str]:
    """
    通过文件名关键词匹配驱动类别

    Returns:
        (类别, 置信度) 元组
    """
    name_without_ext = os.path.splitext(filename)[0]

    for pattern, category in _FILENAME_CATEGORY_RULES:
        if re.search(pattern, name_without_ext):
            return category, "medium"

    return DriverCategory.UNKNOWN, "low"


def _match_by_metadata(
    version_info: dict[str, str]
) -> tuple[DriverCategory, str, str]:
    """
    通过 PE 元数据匹配驱动类别

    Returns:
        (类别, 厂商名, 置信度) 元组
    """
    # 合并所有元数据文本进行匹配
    all_text = " ".join([
        version_info.get("FileDescription", ""),
        version_info.get("ProductName", ""),
        version_info.get("InternalName", ""),
    ])

    # 提取厂商
    company = version_info.get("CompanyName", "")
    vendor = company if company else ""

    # 对合并文本执行类别匹配
    for pattern, category in _FILENAME_CATEGORY_RULES:
        if re.search(pattern, all_text):
            return category, vendor, "medium"

    # 尝试通过厂商名推断类别
    company_lower = company.lower()
    for vendor_key, category in _VENDOR_CATEGORY_HINTS.items():
        if vendor_key in company_lower:
            return category, vendor, "low"

    return DriverCategory.UNKNOWN, vendor, "low"


def _match_by_signer(signer: str) -> DriverCategory:
    """通过签名者名称推断驱动类别"""
    signer_lower = signer.lower()

    signer_rules = [
        ("nvidia", DriverCategory.VIDEO),
        ("advanced micro devices", DriverCategory.VIDEO),
        ("amd", DriverCategory.VIDEO),
        ("realtek", DriverCategory.AUDIO),
        ("synaptics", DriverCategory.TOUCHPAD),
        ("elan", DriverCategory.TOUCHPAD),
        ("killer", DriverCategory.WIFI),
        ("qualcomm", DriverCategory.WIFI),
    ]

    for keyword, category in signer_rules:
        if keyword in signer_lower:
            return category

    return DriverCategory.UNKNOWN


def _extract_vendor_from_signer(signer: str) -> str:
    """从签名者名中提取简洁的厂商名"""
    # 常见厂商名映射
    vendor_map = {
        "intel": "Intel",
        "nvidia": "NVIDIA",
        "realtek": "Realtek",
        "advanced micro": "AMD",
        "dell": "Dell",
        "hewlett": "HP",
        "synaptics": "Synaptics",
        "elan": "ELAN",
        "qualcomm": "Qualcomm",
        "killer": "Killer",
        "samsung": "Samsung",
        "micron": "Micron",
        "broadcom": "Broadcom",
    }

    signer_lower = signer.lower()
    for keyword, vendor in vendor_map.items():
        if keyword in signer_lower:
            return vendor

    # 如果没有匹配到，返回签名者原文（去掉公司后缀）
    cleaned = re.sub(r"(?i)\s*(inc\.?|corp\.?|ltd\.?|co\.?|llc)\.?\s*$", "", signer)
    return cleaned.strip() if len(cleaned) < 50 else signer[:50]


def _detect_installer_type(version_info: dict[str, str]) -> InstallerType:
    """通过 PE 元数据检测安装器类型"""
    for field_name, pattern, installer_type in _INSTALLER_DETECTION_RULES:
        value = version_info.get(field_name, "")
        if value and re.search(pattern, value):
            return installer_type

    return InstallerType.UNKNOWN


def _generate_display_name(version_info: dict[str, str], filename: str) -> str:
    """
    从元数据生成更友好的显示名称

    优先使用 ProductName 或 FileDescription，
    如果都为空则返回空字符串（调用方会保留原文件名）。
    """
    # 优先使用 ProductName
    product = version_info.get("ProductName", "").strip()
    if product and len(product) > 3 and product.lower() != "setup":
        return product

    # 其次使用 FileDescription
    desc = version_info.get("FileDescription", "").strip()
    if desc and len(desc) > 3 and desc.lower() not in ("setup", "installer", "setup application"):
        return desc

    return ""
