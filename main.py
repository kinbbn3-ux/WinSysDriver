# -*- coding: utf-8 -*-
"""
离线驱动安装工具 - 程序入口

功能：
1. 检查管理员权限（驱动安装必须以管理员身份运行）
2. 初始化 Ethereal 视觉主题与字体加载
3. 启动现代化重构后的主窗口
"""

import ctypes
import sys
import os

# 将项目根目录添加到 Python 路径
_PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtCore import Qt

from utils.logger import get_logger
from ui.styles import QSS_MAIN_STYLE, get_res_path

logger = get_logger("Main")


def _is_supported_font_file(path: str) -> bool:
    """在交给 Qt 前过滤被错误保存为 .ttf 的网页或文本文件。"""
    try:
        with open(path, "rb") as stream:
            signature = stream.read(4)
        return signature in {b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1", b"ttcf"}
    except OSError:
        return False


def is_admin() -> bool:
    """检查当前进程是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError):
        return False


def request_admin_restart():
    """提权重新启动程序"""
    try:
        if getattr(sys, 'frozen', False):
            # PyInstaller/Nuitka 编译的 exe
            args = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1)
        else:
            # 纯 Python 脚本运行
            args = " ".join([f'"{arg}"' for arg in sys.argv])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1)
    except Exception as e:
        logger.error(f"请求管理员权限失败: {e}")


def init_fonts():
    """加载 res 目录下的所有自定义字体文件"""
    fonts_dir = get_res_path("fonts")
    if not os.path.exists(fonts_dir):
        logger.warning(f"字体目录不存在: {fonts_dir}")
        return

    # 遍历目录加载所有 .ttf 文件
    loaded_count = 0
    for file_name in os.listdir(fonts_dir):
        if file_name.lower().endswith(".ttf"):
            path = os.path.join(fonts_dir, file_name)
            if os.path.getsize(path) < 1024 or not _is_supported_font_file(path):
                logger.info(f"跳过无效字体资源: {file_name}")
                continue

            font_id = QFontDatabase.addApplicationFont(path)
            if font_id == -1:
                logger.warning(f"加载字体失败: {path}")
            else:
                loaded_count += 1
                logger.info(f"成功加载字体: {file_name}")

    logger.info(f"字体库初始化完成，共加载 {loaded_count} 个字体。")



def main():
    """程序主入口"""
    logger.info("=" * 50)
    logger.info("离线驱动安装工具 v2.0 - Ethereal UI 启动")
    logger.info("=" * 50)

    # === 1. 设置高级 DPI 支持及全局 Application ===
    # os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"  # 交由 Qt6 原生处理缩放，避免 1080P 下二次放大导致出界
    
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
        
    app.setApplicationName("离线驱动安装工具")
    app.setApplicationVersion("2.0.0")

    # === 2. 检查管理员权限 ===
    _is_frozen = getattr(sys, 'frozen', False)  # 是否为打包后的 exe
    if not is_admin():
        if _is_frozen:
            # 打包 exe：强制提权后退出当前进程
            logger.warning("未以管理员权限运行，正在请求提权...")
            request_admin_restart()
            sys.exit(0)
        else:
            # 开发模式：仅记录警告，继续运行（功能受限）
            logger.warning("[开发模式] 非管理员权限运行，驱动安装功能将受限，但 UI 可正常预览。")

    # 加载字体与全局样式
    init_fonts()
    app.setStyleSheet(QSS_MAIN_STYLE)

    # 从样式表配置中动态提取第一优先级字体
    from ui.styles import FONT_FAMILY_BODY
    primary_font = FONT_FAMILY_BODY.split(',')[0].strip("'")
    app_font = QFont(primary_font, 10)
    app.setFont(app_font)

    # === 3. 检查未完成会话 ===
    from core.session_manager import SessionManager
    session_mgr = SessionManager()
    pending_session = session_mgr.load_session()

    # === 4. 启动重构后的主窗口 ===
    from ui.main_window import MainWindow
    window = MainWindow()

    if pending_session:
        # TODO: 使用更漂亮的自定义对话框平替 QMessageBox
        reply = QMessageBox.question(
            window, "恢复安装", "检测到未完成的任务，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            window.restore_session(pending_session)
        else:
            session_mgr.clear_session()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
