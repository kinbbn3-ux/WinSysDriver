# -*- coding: utf-8 -*-
"""
品牌安装顺序配置模块

管理不同品牌（Dell/HP/ASUS 等）的驱动安装顺序模板。
从 res/brand_rules.json 加载配置，支持用户自定义品牌。
"""

import json
import os
import subprocess
from typing import Optional

from models.driver_info import DriverCategory, DriverInfo, CATEGORY_PRIORITY
from utils.logger import get_logger

logger = get_logger("BrandProfiles")

# 资源文件路径
_RES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "res")
)
_BRAND_RULES_PATH = os.path.join(_RES_DIR, "brand_rules.json")

# 类别名称 → 枚举映射
_CATEGORY_NAME_MAP: dict[str, DriverCategory] = {
    cat.value: cat for cat in DriverCategory
}
# 补充英文别名映射
_CATEGORY_NAME_MAP.update({
    "Chipset": DriverCategory.CHIPSET,
    "Management Engine": DriverCategory.MANAGEMENT_ENGINE,
    "Video": DriverCategory.VIDEO,
    "Audio": DriverCategory.AUDIO,
    "Network": DriverCategory.NETWORK,
    "WiFi": DriverCategory.WIFI,
    "Bluetooth": DriverCategory.BLUETOOTH,
    "Storage": DriverCategory.STORAGE,
    "Touchpad": DriverCategory.TOUCHPAD,
    "USB": DriverCategory.USB,
    "BIOS": DriverCategory.BIOS,
    "Firmware": DriverCategory.FIRMWARE,
    "Peripheral": DriverCategory.PERIPHERAL,
})

_MANUFACTURER_BRAND_ALIASES: dict[str, str] = {
    "dell": "Dell",
    "hp": "HP",
    "hewlett-packard": "HP",
    "hewlett packard": "HP",
    "asus": "ASUS",
    "asustek": "ASUS",
}


class BrandProfiles:
    """
    品牌配置管理器

    负责加载、管理品牌安装顺序模板，并据此对驱动列表排序。
    """

    def __init__(self):
        self._profiles: dict[str, dict] = {}
        self._load_profiles()

    def _load_profiles(self):
        """从 JSON 文件加载品牌配置"""
        if not os.path.isfile(_BRAND_RULES_PATH):
            logger.warning(f"品牌配置文件不存在: {_BRAND_RULES_PATH}，使用内置默认配置")
            self._profiles = self._get_default_profiles()
            return

        try:
            with open(_BRAND_RULES_PATH, "r", encoding="utf-8") as f:
                self._profiles = json.load(f)
            self._profiles.setdefault(
                "通用",
                {
                    "install_order": [],
                    "notes": "未识别品牌时使用系统默认优先级，不套用 OEM 专用顺序",
                },
            )
            logger.info(f"已加载品牌配置: {list(self._profiles.keys())}")
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"加载品牌配置文件失败: {e}，使用内置默认配置")
            self._profiles = self._get_default_profiles()

    @staticmethod
    def _get_default_profiles() -> dict[str, dict]:
        """内置默认品牌配置（当 JSON 文件不可用时的回退方案）"""
        return {
            "Dell": {
                "install_order": [
                    "芯片组", "Management Engine", "存储控制器",
                    "显卡", "声卡", "网卡", "无线网卡",
                    "蓝牙", "触控板", "USB 控制器", "外设"
                ],
                "notes": "Dell 驱动通常使用 Dell Update Package (DUP) 封装，支持 /s 静默安装"
            },
            "HP": {
                "install_order": [
                    "芯片组", "存储控制器", "显卡", "声卡",
                    "网卡", "无线网卡", "蓝牙", "触控板", "外设"
                ],
                "notes": "HP 驱动通常使用 SoftPaq 封装"
            },
            "ASUS": {
                "install_order": [
                    "芯片组", "Management Engine", "存储控制器",
                    "显卡", "声卡", "网卡", "无线网卡",
                    "蓝牙", "触控板", "外设"
                ],
                "notes": "ASUS 驱动需要注意 Armoury Crate 相关组件的安装顺序"
            },
            "通用": {
                "install_order": [],
                "notes": "未识别品牌时使用系统默认优先级，不套用 OEM 专用顺序",
            },
        }

    def get_brand_names(self) -> list[str]:
        """获取所有可用的品牌名称"""
        return list(self._profiles.keys())

    def detect_system_brand(self) -> Optional[str]:
        """
        自动识别当前电脑品牌，并映射到已有品牌配置。

        优先读取 Win32_ComputerSystem.Manufacturer；如果无法匹配到配置，
        返回 None，由 UI 保留默认品牌选择。
        """
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_ComputerSystem).Manufacturer",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            logger.warning(f"自动识别电脑品牌失败: {e}")
            return None

        manufacturer = result.stdout.strip()
        if result.returncode != 0 or not manufacturer:
            logger.warning(f"自动识别电脑品牌无有效结果: {result.stderr.strip()}")
            return None

        normalized = manufacturer.lower()
        available_brands = set(self.get_brand_names())
        for keyword, brand in _MANUFACTURER_BRAND_ALIASES.items():
            if keyword in normalized and brand in available_brands:
                logger.info(f"已自动识别电脑品牌: {manufacturer} → {brand}")
                return brand

        for brand in available_brands:
            if brand.lower() in normalized:
                logger.info(f"已自动识别电脑品牌: {manufacturer} → {brand}")
                return brand

        logger.info(f"未找到匹配品牌配置: {manufacturer}")
        return None

    def get_profile(self, brand: str) -> Optional[dict]:
        """获取指定品牌的配置"""
        return self._profiles.get(brand)

    def get_install_order(self, brand: str) -> list[DriverCategory]:
        """
        获取指定品牌的安装顺序（转换为枚举列表）

        Args:
            brand: 品牌名称

        Returns:
            DriverCategory 枚举列表，按安装顺序排列
        """
        profile = self._profiles.get(brand, {})
        order_names = profile.get("install_order", [])

        categories = []
        for name in order_names:
            cat = _CATEGORY_NAME_MAP.get(name)
            if cat:
                categories.append(cat)
            else:
                logger.warning(f"未知的驱动类别名称: {name}")

        return categories

    def sort_drivers(
        self, drivers: list[DriverInfo], brand: str
    ) -> list[DriverInfo]:
        """
        根据品牌配置对驱动列表排序

        品牌配置中定义的类别按顺序排列，
        未在配置中出现的类别按默认优先级排在最后。

        Args:
            drivers: 待排序的驱动列表
            brand: 品牌名称

        Returns:
            排序后的驱动列表（新列表，不修改原列表）
        """
        order = self.get_install_order(brand)

        if not order:
            # 没有找到品牌配置，使用默认优先级排序
            logger.info(f"品牌 '{brand}' 无配置，使用默认优先级排序")
            return sorted(drivers, key=lambda d: d.get_priority())

        # 构建类别 → 顺序索引映射
        order_map = {cat: idx for idx, cat in enumerate(order)}
        max_order = len(order)

        def sort_key(driver: DriverInfo) -> tuple[int, str]:
            # 主排序键：品牌配置中的顺序索引
            primary = order_map.get(driver.category, max_order + CATEGORY_PRIORITY.get(driver.category, 999))
            # 次排序键：同类别内按名称字母序
            secondary = driver.name.lower()
            return (primary, secondary)

        sorted_drivers = sorted(drivers, key=sort_key)
        logger.info(f"已按品牌 '{brand}' 的安装顺序排序 {len(sorted_drivers)} 个驱动")
        return sorted_drivers

    def save_profiles(self):
        """保存当前配置到 JSON 文件"""
        os.makedirs(os.path.dirname(_BRAND_RULES_PATH), exist_ok=True)
        try:
            with open(_BRAND_RULES_PATH, "w", encoding="utf-8") as f:
                json.dump(self._profiles, f, ensure_ascii=False, indent=2)
            logger.info("品牌配置已保存")
        except OSError as e:
            logger.error(f"保存品牌配置失败: {e}")

    def add_brand(self, brand: str, install_order: list[str], notes: str = ""):
        """
        添加或更新品牌配置

        Args:
            brand: 品牌名称
            install_order: 安装顺序（类别名称列表）
            notes: 备注信息
        """
        self._profiles[brand] = {
            "install_order": install_order,
            "notes": notes,
        }
        self.save_profiles()
        logger.info(f"已添加/更新品牌配置: {brand}")

    def remove_brand(self, brand: str) -> bool:
        """删除品牌配置"""
        if brand in self._profiles:
            del self._profiles[brand]
            self.save_profiles()
            logger.info(f"已删除品牌配置: {brand}")
            return True
        return False
