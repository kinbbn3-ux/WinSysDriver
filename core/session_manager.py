# -*- coding: utf-8 -*-
"""
会话管理器

负责安装进度的持久化保存和恢复，实现重启后自动继续安装。
通过 Windows RunOnce 注册表项实现重启后自启动。
"""

import json
import os
import sys
import uuid
import winreg
from datetime import datetime
from typing import Optional

from models.driver_info import DriverInfo
from utils.logger import get_logger

logger = get_logger("SessionManager")

# 会话文件保存路径
_SESSION_DIR = os.path.join(
    os.path.abspath(os.path.dirname(os.path.dirname(__file__))),
    "data"
)
_SESSION_FILE = os.path.join(_SESSION_DIR, "install_session.json")

# RunOnce 注册表路径
_RUNONCE_KEY = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
_RUNONCE_VALUE_NAME = "DriverInstaller_Resume"


class SessionManager:
    """
    安装会话管理器

    职责：
    1. 当驱动安装因需要重启而中断时，保存当前进度
    2. 在 Windows RunOnce 注册表中注册自启动
    3. 程序启动时检测并恢复未完成的会话
    4. 安装全部完成后清理会话数据和注册表项
    """

    def __init__(self):
        os.makedirs(_SESSION_DIR, exist_ok=True)

    def save_session(
        self,
        drivers: list[DriverInfo],
        current_index: int,
        driver_folder: str,
        brand: str,
    ):
        """
        保存安装会话

        Args:
            drivers: 完整的驱动列表
            current_index: 下一个待安装的索引
            driver_folder: 驱动文件夹路径
            brand: 当前选择的品牌
        """
        session_data = {
            "session_id": str(uuid.uuid4()),
            "created_at": datetime.now().isoformat(),
            "driver_folder": driver_folder,
            "brand": brand,
            "total_count": len(drivers),
            "current_index": current_index,
            "drivers": [d.to_dict() for d in drivers],
            "status": "waiting_reboot",
        }

        try:
            with open(_SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
            logger.info(f"会话已保存: {session_data['session_id']}")
            logger.info(f"  进度: {current_index}/{len(drivers)}")

            # 注册 RunOnce 自启动
            self._register_runonce()

        except OSError as e:
            logger.error(f"保存会话失败: {e}")

    def load_session(self) -> Optional[dict]:
        """
        加载未完成的会话

        Returns:
            会话数据字典，如果没有未完成的会话则返回 None
        """
        if not os.path.isfile(_SESSION_FILE):
            return None

        try:
            with open(_SESSION_FILE, "r", encoding="utf-8") as f:
                session_data = json.load(f)

            # 验证会话数据的完整性
            required_keys = ["session_id", "drivers", "current_index", "total_count"]
            for key in required_keys:
                if key not in session_data:
                    logger.warning(f"会话数据缺少必要字段: {key}，忽略此会话")
                    return None

            # 检查会话状态
            if session_data.get("status") != "waiting_reboot":
                logger.info("会话状态不是 'waiting_reboot'，忽略")
                return None

            logger.info(f"加载会话: {session_data['session_id']}")
            logger.info(f"  创建时间: {session_data.get('created_at', '未知')}")
            logger.info(f"  进度: {session_data['current_index']}/{session_data['total_count']}")

            return session_data

        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"加载会话失败: {e}")
            return None

    def restore_drivers(self, session_data: dict) -> tuple[list[DriverInfo], int]:
        """
        从会话数据恢复驱动列表

        Args:
            session_data: load_session() 返回的会话数据

        Returns:
            (驱动列表, 起始索引) 元组
        """
        drivers = []
        for driver_dict in session_data.get("drivers", []):
            try:
                driver = DriverInfo.from_dict(driver_dict)
                drivers.append(driver)
            except Exception as e:
                logger.error(f"恢复驱动信息失败: {e}")

        start_index = session_data.get("current_index", 0)

        logger.info(f"已恢复 {len(drivers)} 个驱动，从索引 {start_index} 继续")
        return drivers, start_index

    def clear_session(self):
        """
        清除会话数据和 RunOnce 注册表项

        在安装全部完成或用户选择不恢复时调用。
        """
        # 删除会话文件
        if os.path.isfile(_SESSION_FILE):
            try:
                os.remove(_SESSION_FILE)
                logger.info("会话文件已删除")
            except OSError as e:
                logger.error(f"删除会话文件失败: {e}")

        # 清除 RunOnce 注册表项
        self._remove_runonce()

    def _register_runonce(self):
        """
        在 Windows RunOnce 注册表中注册自启动

        RunOnce 中的值在执行一次后会自动删除，
        确保程序只在下次重启时自动运行一次。
        """
        try:
            # 构造启动命令
            exe_path = sys.executable
            script_path = os.path.abspath(
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
            )

            # 如果是通过 python.exe 运行的脚本
            if exe_path.lower().endswith("python.exe") or exe_path.lower().endswith("pythonw.exe"):
                command = f'"{exe_path}" "{script_path}"'
            else:
                # 如果是打包后的 exe
                command = f'"{exe_path}"'

            # 写入注册表
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                _RUNONCE_KEY,
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, _RUNONCE_VALUE_NAME, 0, winreg.REG_SZ, command)
            winreg.CloseKey(key)

            logger.info(f"已注册 RunOnce 自启动: {command}")

        except (OSError, WindowsError) as e:
            logger.error(f"注册 RunOnce 失败: {e}")

    def _remove_runonce(self):
        """清除 RunOnce 注册表项"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                _RUNONCE_KEY,
                0,
                winreg.KEY_SET_VALUE,
            )
            try:
                winreg.DeleteValue(key, _RUNONCE_VALUE_NAME)
                logger.info("已清除 RunOnce 注册表项")
            except FileNotFoundError:
                pass  # 值不存在，无需处理
            winreg.CloseKey(key)
        except (OSError, WindowsError) as e:
            logger.debug(f"清除 RunOnce 注册表项异常（可忽略）: {e}")
