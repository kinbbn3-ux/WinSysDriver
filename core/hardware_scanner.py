# -*- coding: utf-8 -*-
"""
硬件扫描器

通过 WMI (Windows Management Instrumentation) 扫描当前系统的
硬件设备信息及驱动状态，识别缺失或使用通用驱动的设备。

同时提供与驱动文件夹的交叉比对功能。
"""

import re
import subprocess
from typing import Optional

from models.device_info import (
    DeviceInfo, DeviceStatus, MatchStatus, IssueLevel,
    CRITICAL_DEVICE_CLASSES
)
from models.driver_info import DriverInfo, DriverCategory
from utils.logger import get_logger

logger = get_logger("HardwareScanner")

# 已知的通用/基础驱动提供商（使用这些驱动意味着未安装专用驱动）
_GENERIC_DRIVER_PROVIDERS = {
    "microsoft",
    "microsoft corporation",
    "标准",          # 中文 Windows 中的"标准 xxx 控制器"
    "(标准",
    "generic",
}

# 核心硬件类别，这些条目不仅重要，而且必须在列表中显示
CORE_HARDWARE_CLASSES = {
    "Display", "Net", "Media", "AudioEndpoint", 
    "HDC", "SCSIAdapter", "Bluetooth", "Firmware", "System"
}

# 设备类别 → DriverCategory 映射（用于交叉比对）
_DEVICE_CLASS_TO_DRIVER_CATEGORY: dict[str, list[DriverCategory]] = {
    "Display": [DriverCategory.VIDEO],
    "Net": [DriverCategory.NETWORK, DriverCategory.WIFI],
    "Media": [DriverCategory.AUDIO],
    "AudioEndpoint": [DriverCategory.AUDIO],
    "HDC": [DriverCategory.STORAGE],
    "SCSIAdapter": [DriverCategory.STORAGE],
    "Bluetooth": [DriverCategory.BLUETOOTH],
    "Mouse": [DriverCategory.TOUCHPAD],
    "HIDClass": [DriverCategory.TOUCHPAD],
    "USB": [DriverCategory.USB],
    "Firmware": [DriverCategory.FIRMWARE],
    "System": [DriverCategory.CHIPSET, DriverCategory.MANAGEMENT_ENGINE],
}

# 需要过滤的无关设备名称关键词
_IGNORE_DEVICE_KEYWORDS = [
    "Microsoft", "Root", "UMBus", "ACPI", "Composite",
    "Volume", "Disk", "Partition", "UEFI", "PnP", "Enumerator",
    "Logical Disk", "Generic Bus", "Legacy", "Software Device",
    "Manager", "Bridge" # 泛化的控制器如果没有错误则过滤
]


def scan_hardware() -> list[DeviceInfo]:
    """
    扫描当前系统的硬件设备及驱动状态

    使用 PowerShell 调用 WMI 的 Win32_PnPEntity 获取设备信息，
    分析每个设备的驱动安装状态。

    Returns:
        DeviceInfo 列表，按关键程度和类别排序
    """
    logger.info("开始扫描系统硬件...")
    devices: list[DeviceInfo] = []

    try:
        # 使用 PowerShell 查询 WMI 设备信息
        # 获取：名称、设备ID、硬件ID、类别、制造商、驱动版本、状态码、驱动提供商
        ps_script = (
            "Get-CimInstance Win32_PnPEntity | "
            "Select-Object Name, DeviceID, "
            "@{N='HardwareIDs';E={($_.HardwareID -join '|')}}, "
            "PNPClass, Manufacturer, DriverVersion, "
            "ConfigManagerErrorCode, "
            "@{N='DriverProvider';E={"
            "(Get-CimInstance Win32_PnPSignedDriver | "
            "Where-Object {$_.DeviceID -eq $_.DeviceID} | "
            "Select-Object -First 1).DriverProviderName"
            "}} | "
            "ConvertTo-Csv -NoTypeInformation"
        )

        # 简化版本 - 先获取基本设备信息
        ps_basic = (
            "Get-CimInstance Win32_PnPEntity | "
            "Select-Object Name, DeviceID, PNPClass, Manufacturer, "
            "ConfigManagerErrorCode, DriverVersion | "
            "ConvertTo-Csv -NoTypeInformation"
        )

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_basic],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if result.returncode != 0:
            logger.error(f"WMI 查询失败: {result.stderr}")
            return []

        # 解析 CSV 输出
        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            logger.warning("WMI 查询返回空结果")
            return []

        # 解析表头
        headers = _parse_csv_line(lines[0])

        for line in lines[1:]:
            fields = _parse_csv_line(line)
            if len(fields) < len(headers):
                continue

            row = dict(zip(headers, fields))

            # 创建设备信息
            device = DeviceInfo(
                name=row.get("Name", "").strip(),
                device_id=row.get("DeviceID", "").strip(),
                device_class=row.get("PNPClass", "").strip(),
                manufacturer=row.get("Manufacturer", "").strip(),
                driver_version=row.get("DriverVersion", "").strip(),
            )

            # 跳过空名称或无意义设备
            if not device.name or _should_ignore_device(device):
                continue

            # 分析驱动状态
            error_code_str = row.get("ConfigManagerErrorCode", "0").strip()
            try:
                error_code = int(error_code_str)
            except ValueError:
                error_code = 0

            device.status = _analyze_device_status(device, error_code)
            device.status_detail = _get_status_detail(device.status, error_code)
            
            # --- 智能优先级与人说话术 (NEW) ---
            _assign_issue_and_status(device, error_code)

            devices.append(device)

        # 处理器聚合逻辑
        devices = _aggregate_processors(devices)

        # 获取驱动提供商信息（用于检测通用驱动）
        _enrich_with_driver_providers(devices)

        # 最终过滤标记：除了关键错误，其余非核心类别均标记为 is_filtered
        for dev in devices:
            if dev.issue_level == IssueLevel.INFO:
                if dev.device_class not in CORE_HARDWARE_CLASSES or _should_soft_ignore(dev):
                    dev.is_filtered = True

    except subprocess.TimeoutExpired:
        logger.error("WMI 查询超时")
    except Exception as e:
        logger.error(f"硬件扫描异常: {e}")

    # 排序：关键设备优先，缺失驱动优先
    devices.sort(key=lambda d: (
        not d.is_critical,
        d.status != DeviceStatus.MISSING,
        d.status != DeviceStatus.GENERIC,
        d.class_display_name,
        d.name,
    ))

    logger.info(f"扫描完成: {len(devices)} 个设备")
    _log_summary(devices)

    return devices


def cross_match(
    devices: list[DeviceInfo],
    drivers: list[DriverInfo],
) -> list[DeviceInfo]:
    """
    将缺失/通用驱动的设备与驱动文件夹中的驱动进行交叉比对

    匹配逻辑：
    1. 设备类别 → 驱动类别映射
    2. 设备制造商 → 驱动厂商名匹配
    3. 设备名称关键词 → 驱动名称关键词匹配

    Args:
        devices: 硬件扫描结果
        drivers: 驱动文件夹的识别结果

    Returns:
        更新了匹配状态的设备列表
    """
    logger.info(f"开始交叉比对: {len(devices)} 个设备 × {len(drivers)} 个驱动")

    for device in devices:
        # 驱动正常的设备不需要匹配
        if device.status == DeviceStatus.OK:
            device.match_status = MatchStatus.NOT_NEEDED
            continue

        if device.status in (DeviceStatus.MISSING, DeviceStatus.GENERIC, DeviceStatus.ERROR):
            matched_driver = _find_matching_driver(device, drivers)
            if matched_driver:
                device.match_status = MatchStatus.MATCHED
                device.matched_driver_name = matched_driver.name
                logger.info(f"  匹配成功: {device.name} → {matched_driver.name}")
            else:
                device.match_status = MatchStatus.NOT_MATCHED
                logger.info(f"  未匹配: {device.name}")
        else:
            device.match_status = MatchStatus.NOT_CHECKED

    # 统计
    matched = sum(1 for d in devices if d.match_status == MatchStatus.MATCHED)
    not_matched = sum(1 for d in devices if d.match_status == MatchStatus.NOT_MATCHED)
    logger.info(f"比对完成: 已匹配 {matched}, 未匹配(需下载) {not_matched}")

    return devices


def _find_matching_driver(
    device: DeviceInfo, drivers: list[DriverInfo]
) -> Optional[DriverInfo]:
    """
    为单个设备查找匹配的驱动

    按优先级尝试多种匹配策略。
    """
    # 获取设备对应的驱动类别列表
    target_categories = _DEVICE_CLASS_TO_DRIVER_CATEGORY.get(device.device_class, [])

    # 策略1：类别 + 厂商名匹配
    if target_categories and device.manufacturer:
        manufacturer_lower = device.manufacturer.lower()
        for driver in drivers:
            if driver.category in target_categories:
                # 检查厂商名
                if (manufacturer_lower in driver.vendor.lower() or
                    manufacturer_lower in driver.company_name.lower() or
                    manufacturer_lower in driver.signer.lower()):
                    return driver

    # 策略2：类别匹配 + 设备名称关键词
    if target_categories:
        device_keywords = _extract_keywords(device.name)
        for driver in drivers:
            if driver.category in target_categories:
                driver_text = f"{driver.name} {driver.file_description} {driver.product_name}"
                driver_text_lower = driver_text.lower()
                # 至少一个关键词匹配
                if any(kw in driver_text_lower for kw in device_keywords):
                    return driver

    # 策略3：仅类别匹配（最宽松）
    if target_categories:
        for driver in drivers:
            if driver.category in target_categories:
                return driver

    return None


def _extract_keywords(text: str) -> list[str]:
    """从文本中提取有意义的关键词（小写）"""
    # 移除常见无意义词
    stop_words = {"controller", "adapter", "device", "compatible", "standard", "pci", "express"}
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return [w for w in words if w not in stop_words]


def _parse_csv_line(line: str) -> list[str]:
    """解析 CSV 行（处理带引号的字段）"""
    fields = []
    current = ""
    in_quotes = False

    for char in line.strip():
        if char == '"':
            in_quotes = not in_quotes
        elif char == ',' and not in_quotes:
            fields.append(current.strip().strip('"'))
            current = ""
        else:
            current += char

    fields.append(current.strip().strip('"'))
    return fields


def _should_ignore_device(device: DeviceInfo) -> bool:
    """判断设备是否应该被忽略（系统内部虚拟设备等）"""
    name_lower = device.name.lower()

    # 过滤软件/虚拟设备
    if device.device_class in ("SoftwareDevice", "SoftwareComponent", ""):
        return True

    # 过滤名称中包含特定关键词的设备
    for keyword in _IGNORE_DEVICE_KEYWORDS:
        if keyword.lower() in name_lower:
            return True

    return False


def _analyze_device_status(device: DeviceInfo, error_code: int) -> DeviceStatus:
    """
    分析设备的驱动状态

    ConfigManagerErrorCode:
    0 = 正常工作
    1 = 设备未正确配置
    10 = 设备无法启动
    22 = 设备被禁用
    28 = 驱动未安装
    31 = 设备工作不正常
    """
    if error_code == 0:
        # 正常工作，但可能是通用驱动
        return DeviceStatus.OK
    elif error_code == 28:
        return DeviceStatus.MISSING
    elif error_code == 22:
        # 设备被禁用，不算缺失
        return DeviceStatus.OK
    elif error_code in (1, 10, 31):
        return DeviceStatus.ERROR
    else:
        return DeviceStatus.UNKNOWN


def _get_status_detail(status: DeviceStatus, error_code: int) -> str:
    """获取状态的详细说明"""
    details = {
        DeviceStatus.OK: "驱动已正确安装",
        DeviceStatus.GENERIC: "使用通用驱动，建议安装专用驱动",
        DeviceStatus.MISSING: f"驱动缺失（错误码: {error_code}）",
        DeviceStatus.ERROR: f"驱动存在问题（错误码: {error_code}）",
        DeviceStatus.UNKNOWN: "无法确定驱动状态",
    }
    return details.get(status, "")


def _enrich_with_driver_providers(devices: list[DeviceInfo]):
    """
    查询驱动提供商信息，识别使用通用驱动的设备

    通过 Win32_PnPSignedDriver 获取每个设备的驱动提供商。
    如果提供商是 Microsoft 等通用提供商，则标记为通用驱动。
    """
    try:
        ps_cmd = (
            "Get-CimInstance Win32_PnPSignedDriver | "
            "Where-Object { $_.DeviceName -ne $null } | "
            "Select-Object DeviceID, DriverProviderName | "
            "ConvertTo-Csv -NoTypeInformation"
        )

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if result.returncode != 0:
            logger.debug("查询驱动提供商失败，跳过通用驱动检测")
            return

        # 构建 DeviceID → DriverProvider 映射
        provider_map: dict[str, str] = {}
        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return

        headers = _parse_csv_line(lines[0])
        for line in lines[1:]:
            fields = _parse_csv_line(line)
            if len(fields) >= 2:
                row = dict(zip(headers, fields))
                dev_id = row.get("DeviceID", "").strip()
                provider = row.get("DriverProviderName", "").strip()
                if dev_id and provider:
                    provider_map[dev_id] = provider

        # 更新设备状态
        for device in devices:
            if device.status == DeviceStatus.OK and device.is_critical:
                provider = provider_map.get(device.device_id, "")
                if provider and provider.lower() in _GENERIC_DRIVER_PROVIDERS:
                    device.status = DeviceStatus.GENERIC
                    device.status_detail = f"使用通用驱动（{provider}），建议安装专用驱动"
                    device.issue_level = IssueLevel.WARNING
                    device.human_readable_status = "通用驱动 · 建议安装专用驱动"

    except Exception as e:
        logger.debug(f"查询驱动提供商异常: {e}")


def _aggregate_processors(devices: list[DeviceInfo]) -> list[DeviceInfo]:
    """将多个逻辑处理器条目合并为一条"""
    processors = [d for d in devices if d.device_class == "Processor"]
    if not processors:
        return devices
    
    # 保持非处理器设备
    new_devices = [d for d in devices if d.device_class != "Processor"]
    
    # 聚合处理器
    first = processors[0]
    core_count = len(processors)
    agg_name = f"{first.name} ({core_count} Cores)"
    
    processor_node = DeviceInfo(
        name=agg_name,
        device_id=first.device_id,
        device_class="Processor",
        manufacturer=first.manufacturer,
        driver_version=first.driver_version,
        status=first.status,
        issue_level=first.issue_level,
        human_readable_status=f"正常运行中",
        is_filtered=True # 处理器驱动通常由 BIOS/系统管理，默认隐藏
    )
    new_devices.append(processor_node)
    return new_devices


def _assign_issue_and_status(device: DeviceInfo, error_code: int):
    """为设备分配可视化优先级和友好描述"""
    if error_code != 0 and error_code != 22: # 22 是禁用
        device.issue_level = IssueLevel.CRITICAL
        if error_code == 28:
            device.human_readable_status = f"{device.class_display_name} · 驱动缺失，设备无法使用"
        else:
            device.human_readable_status = f"设备故障 (错误码: {error_code})"
    elif "Microsoft" in device.manufacturer and device.device_class in ("Display", "Net", "Media"):
        # 通用驱动警告
        device.issue_level = IssueLevel.WARNING
        device.human_readable_status = "通用驱动 · 性能受限，建议安装专用驱动"
    else:
        device.issue_level = IssueLevel.INFO
        device.human_readable_status = "运行正常"


def _should_soft_ignore(device: DeviceInfo) -> bool:
    """更精细的次要设备判断"""
    low_priority_keywords = ["HID", "USB Hub", "Generic", "Standard", "PCI Bus"]
    return any(kw in device.name for kw in low_priority_keywords)


def _log_summary(devices: list[DeviceInfo]):
    """输出扫描结果摘要"""
    ok = sum(1 for d in devices if d.status == DeviceStatus.OK)
    generic = sum(1 for d in devices if d.status == DeviceStatus.GENERIC)
    missing = sum(1 for d in devices if d.status == DeviceStatus.MISSING)
    error = sum(1 for d in devices if d.status == DeviceStatus.ERROR)

    logger.info(f"  ✅ 正常: {ok}")
    logger.info(f"  🔶 通用驱动: {generic}")
    logger.info(f"  ⚠️ 缺失: {missing}")
    logger.info(f"  ❌ 错误: {error}")
