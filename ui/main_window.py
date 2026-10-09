# -*- coding: utf-8 -*-
"""
主窗口 - Ethereal 重构版
"""

import os
import subprocess
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QLabel,
    QMessageBox, QStatusBar, QFrame, QComboBox, QCheckBox, QInputDialog
)
from PySide6.QtCore import Qt, Slot, QThread, Signal, QTimer

from ui.driver_list_widget import DriverListWidget
from ui.progress_widget import ProgressWidget
from ui.hardware_status_widget import HardwareStatusWidget
from ui.dashboard_widget import DashboardWidget
from ui.scan_animation_widget import ScanAnimationWidget
from ui.system_specs_widget import SystemSpecsWidget
from ui.software_list_widget import SoftwareListWidget
from ui.styles import (
    COLOR_ON_SURFACE_VARIANT, COLOR_WHITE, COLOR_PRIMARY, FONT_FAMILY_BODY, FONT_FAMILY_TITLE, COLOR_ON_SURFACE, FONT_FAMILY_MONO
)

from core.driver_analyzer import scan_folder
from core.hardware_scanner import cross_match
from core.brand_profiles import BrandProfiles
from core.install_manager import InstallManager
from core.session_manager import SessionManager
from core.software_scanner import SoftwareScanWorker
from core.software_installer import SoftwareInstaller
from models.driver_info import DriverInfo, InstallStatus
from models.package_info import PackageInfo
from utils.logger import get_logger

logger = get_logger("MainWindow")


class _DriverScanWorker(QThread):
    """异步扫描驱动文件夹的工作线程"""
    scan_finished = Signal(list)
    scan_error = Signal(str)

    def __init__(self, folder_path: str):
        super().__init__()
        self.folder_path = folder_path

    def run(self):
        try:
            from core.driver_analyzer import scan_folder
            drivers = scan_folder(self.folder_path)
            self.scan_finished.emit(drivers)
        except Exception as e:
            self.scan_error.emit(str(e))


class MainWindow(QMainWindow):
    """
    主窗口 - 现代化重构版
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # === 初始化核心模块 ===
        self._brand_profiles = BrandProfiles()
        self._install_manager = InstallManager(self)
        self._session_manager = SessionManager()

        # === 状态变量 ===
        self._current_folder: str = ""
        self._current_brand: str = self._brand_profiles.detect_system_brand() or "通用"
        self._drivers: list[DriverInfo] = []
        self._resume_start_index = 0

        # 软件安装相关状态
        self._sw_folder: str = ""
        self._sw_packages: list[PackageInfo] = []
        self._software_installer = SoftwareInstaller(self)
        self._sw_scan_worker: SoftwareScanWorker | None = None
        self._driver_scan_worker: _DriverScanWorker | None = None

        # === 初始化 UI ===
        self._setup_ui()
        self._connect_signals()

        # === 窗口属性 ===
        self.setWindowTitle("离线驱动安装工具 v2.0")
        self.setMinimumSize(1200, 768)
        self.resize(1280, 800)

    def _setup_ui(self):
        """初始化 UI：左侧导航 + 右侧内容层级"""
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        
        self._root_layout = QHBoxLayout(central)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        # === 1. 左侧导航栏 ===
        self._sidebar = QFrame()
        self._sidebar.setFixedWidth(240)
        self._sidebar.setObjectName("sidebar")
        
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(20, 30, 20, 20)
        sidebar_layout.setSpacing(10)

        # 品牌文本 Logo
        title_label = QLabel("ETHEREAL\nTECHNICIAN")
        title_label.setStyleSheet(f"font-family: {FONT_FAMILY_TITLE}; font-weight: 800; font-size: 20px; color: {COLOR_PRIMARY}; line-height: 1.2;")
        sidebar_layout.addWidget(title_label)
        
        sidebar_layout.addSpacing(40)

        # 导航按鈕组
        self._nav_group = []
        self._btn_nav_system    = self._create_nav_button("🖥️ 系统概览", True)
        self._btn_nav_dashboard = self._create_nav_button("📊 监控概览", False)
        self._btn_nav_install   = self._create_nav_button("📋 驱动安装", False)
        self._btn_nav_software  = self._create_nav_button("📦 软件安装", False)  # 新增
        self._btn_nav_hardware  = self._create_nav_button("🧩 硬件状态说明", False)

        sidebar_layout.addWidget(self._btn_nav_system)
        sidebar_layout.addWidget(self._btn_nav_dashboard)
        sidebar_layout.addWidget(self._btn_nav_install)
        sidebar_layout.addWidget(self._btn_nav_software)
        sidebar_layout.addWidget(self._btn_nav_hardware)
        
        sidebar_layout.addStretch()

        self._root_layout.addWidget(self._sidebar)

        # === 2. 右侧主内容区 ===
        self._main_content = QWidget()
        content_layout = QVBoxLayout(self._main_content)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(0)

        # 中央堆栈
        self._stack = QStackedWidget()
        
        # 页面 0: 硬件系统概览 (首屏)
        self._system_specs = SystemSpecsWidget()
        self._stack.addWidget(self._system_specs)

        # 页面 1: 仪表盘概览
        self._dashboard = DashboardWidget()
        self._stack.addWidget(self._dashboard)
        
        # 页面 2: 驱动安装
        self._page_install = QWidget()
        install_layout = QVBoxLayout(self._page_install)
        install_layout.setContentsMargins(0, 0, 0, 0)
        install_layout.setSpacing(15)
        
        # --- 顶部功能区 (融合扫描设置) ---
        top_header = QWidget()
        top_layout = QHBoxLayout(top_header)
        top_layout.setContentsMargins(0, 0, 0, 15)
        
        # 3.1 标题文字
        title_box = QVBoxLayout()
        install_title = QLabel("驱动安装助手")
        install_title.setStyleSheet(f"font-size: 26px; font-weight: 800; color: {COLOR_ON_SURFACE}; font-family: {FONT_FAMILY_TITLE};")
        self._install_subtitle = QLabel("请先选择驱动源文件夹以开始检测")
        self._install_subtitle.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 13px; margin-top: 2px;")
        title_box.addWidget(install_title)
        title_box.addWidget(self._install_subtitle)
        top_layout.addLayout(title_box)
        
        top_layout.addStretch()
        
        # 3.2 动态设置区 (品牌偏好 + 递归)
        pref_box = QHBoxLayout()
        pref_box.setSpacing(10)
        
        brand_lbl = QLabel("品牌识别偏好:")
        brand_lbl.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-weight: bold; font-size: 12px;")
        pref_box.addWidget(brand_lbl)
        
        self._top_brand_combo = QComboBox()
        self._top_brand_combo.addItems(self._brand_profiles.get_brand_names())
        self._top_brand_combo.setCurrentText(self._current_brand)
        self._top_brand_combo.setFixedWidth(120)
        self._top_brand_combo.setFixedHeight(34)
        self._top_brand_combo.setStyleSheet(f"background-color: {COLOR_WHITE}; border: 1px solid #dcdcdc; border-radius: 8px; padding-left: 10px;")
        self._top_brand_combo.currentTextChanged.connect(self._on_brand_changed)
        pref_box.addWidget(self._top_brand_combo)
        
        self._top_check_recursive = QCheckBox("递归搜索")
        self._top_check_recursive.setChecked(True)
        self._top_check_recursive.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 12px;")
        pref_box.addWidget(self._top_check_recursive)

        self._check_signature = QCheckBox("安装前校验数字签名")
        self._check_signature.setChecked(True)
        self._check_signature.setToolTip("开启后会阻止未通过签名校验的驱动；关闭后由用户自行承担风险。")
        self._check_signature.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 12px;")
        pref_box.addWidget(self._check_signature)
        
        top_layout.addLayout(pref_box)
        top_layout.addSpacing(20)

        # 3.3 动作按钮组
        self._btn_top_folder = QPushButton(" 选择文件夹 ")
        self._btn_top_folder.setObjectName("primary_button")
        self._btn_top_folder.setFixedHeight(40)
        self._btn_top_folder.setMinimumWidth(120)
        self._btn_top_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_top_folder.clicked.connect(self._on_browse_folder)
        top_layout.addWidget(self._btn_top_folder)

        self._lbl_path_crumb = QLabel(" 未选择路径 ")
        self._lbl_path_crumb.setStyleSheet(f"background-color: #f1f4f8; color: #7a869a; border-radius: 17px; padding: 0 15px; font-size: 12px; font-family: {FONT_FAMILY_MONO}; height: 34px;")
        self._lbl_path_crumb.setMinimumWidth(150)
        top_layout.addWidget(self._lbl_path_crumb)

        install_layout.addWidget(top_header)
        
        # 3.4 列表与进度栏
        self._driver_list = DriverListWidget()
        install_layout.addWidget(self._driver_list, 1)
        
        self._progress_panel = ProgressWidget()
        install_layout.addWidget(self._progress_panel)
        
        self._stack.addWidget(self._page_install)

        # 页面 3: 软件安装 (新增)
        self._page_software = self._build_software_page()
        self._stack.addWidget(self._page_software)

        # 页面 4: 硬件探测比对透视
        self._hardware_status = HardwareStatusWidget()
        self._stack.addWidget(self._hardware_status)

        # 页面 5: 动画过渡页 (用于扫描中展示)
        self._scan_anim_page = ScanAnimationWidget()
        self._stack.addWidget(self._scan_anim_page)
        
        content_layout.addWidget(self._stack)
        self._root_layout.addWidget(self._main_content)

        # === 3. 状态栏 ===
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.setStyleSheet(f"background-color: transparent; color: {COLOR_ON_SURFACE_VARIANT};")

    def _create_nav_button(self, text: str, checked: bool) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("nav_button")
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setFixedHeight(50)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # 使用 lambda 捕获按钮引用
        btn.clicked.connect(lambda: self._on_nav_clicked(btn))
        self._nav_group.append(btn)
        return btn

    @Slot(object)
    def _on_nav_clicked(self, clicked_btn: QPushButton):
        for btn in self._nav_group:
            btn.setChecked(btn == clicked_btn)
        
        index = self._nav_group.index(clicked_btn)
        self._stack.setCurrentIndex(index)

    def _connect_signals(self):
        """信号槽连接"""
        # 进度面板控制
        self._progress_panel.start_clicked.connect(self._on_start_install)
        self._progress_panel.pause_clicked.connect(self._install_manager.pause)
        self._progress_panel.resume_clicked.connect(self._install_manager.resume)
        self._progress_panel.cancel_clicked.connect(self._on_cancel_install)

        # 安装管理器
        self._install_manager.progress_updated.connect(self._on_progress_updated)
        self._install_manager.install_finished.connect(self._on_install_finished)
        self._install_manager.reboot_required.connect(self._on_reboot_required)
        self._install_manager.all_completed.connect(self._on_all_completed)
        self._install_manager.cancelled.connect(self._on_install_cancelled)

        # 硬件与配置
        self._hardware_status.scan_completed.connect(self._on_hardware_scan_completed)
        self._hardware_status.scan_started.connect(self._on_hardware_scan_started)

        self._software_installer.progress_updated.connect(self._on_sw_progress_updated)
        self._software_installer.install_finished.connect(self._on_sw_install_finished)
        self._software_installer.all_completed.connect(self._on_sw_all_completed)
        self._software_installer.cancelled.connect(self._on_sw_cancelled)
        
        # 硬件联动定向修复
        self._hardware_status.fix_requested.connect(self._on_fix_requested)
    
    @Slot()
    def _on_browse_folder(self):
        """响应顶部 Header 的文件夹选择按钮"""
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "选择驱动源文件夹")
        if folder:
            self._on_folder_selected(folder)

    @Slot(str)
    def _on_folder_selected(self, folder: str):
        self._current_folder = folder
        # 同步 Header 的显示
        self._lbl_path_crumb.setText(f" {folder[:20]}... " if len(folder) > 20 else f" {folder} ")
        self._scan_drivers()

    @Slot(str)
    def _on_brand_changed(self, brand: str):
        self._current_brand = brand
        # 同步各处下拉框
        self._top_brand_combo.blockSignals(True)
        self._top_brand_combo.setCurrentText(brand)
        self._top_brand_combo.blockSignals(False)
        
        if self._drivers:
            self._drivers = self._brand_profiles.sort_drivers(self._drivers, brand)
            self._driver_list.set_drivers(self._drivers)

    def _scan_drivers(self):
        """主入口：启动异步扫描驱动"""
        if not self._current_folder:
            return
            
        self._statusbar.showMessage(f"正在准备分析: {self._current_folder}...")
        
        # 1. 挂起 UI 交互
        self._lock_ui(True)
        for btn in self._nav_group:
            btn.setChecked(False)
        self._stack.setCurrentIndex(5)  # 页面 5: 动画过渡页
        self._scan_anim_page.start("搜寻驱动资源...")

        # 2. 停止旧线程（防重入）
        if self._driver_scan_worker and self._driver_scan_worker.isRunning():
            self._driver_scan_worker.terminate() # 强制停止（如果是 WMI 等阻塞操作）
            self._driver_scan_worker.wait()

        # 3. 创建并启动工作线程
        self._driver_scan_worker = _DriverScanWorker(self._current_folder)
        self._driver_scan_worker.scan_finished.connect(self._on_driver_scan_finished)
        self._driver_scan_worker.scan_error.connect(self._on_driver_scan_error)
        self._driver_scan_worker.start()
        logger.info(f"开启异步驱动扫描: {self._current_folder}")

    @Slot(list)
    def _on_driver_scan_finished(self, drivers: list):
        """驱动扫描成功回调 (工作线程)"""
        try:
            if not drivers:
                QMessageBox.information(self, "未找到驱动", "该文件夹下未检测到可用的驱动程序。")
                self._on_nav_clicked(self._btn_nav_install)
                return
                
            # 排序与填充列表
            self._drivers = self._brand_profiles.sort_drivers(drivers, self._current_brand)
            self._driver_list.set_drivers(self._drivers)
            self._install_subtitle.setText(f"检测到 {len(self._drivers)} 个可更新的离线驱动程序")
            
            self._progress_panel.reset()
            self._try_cross_match()
            self._on_nav_clicked(self._btn_nav_install)
            self._statusbar.showMessage("扫描完成")
        finally:
            self._scan_anim_page.stop()
            self._lock_ui(False)
            self.unsetCursor()

    @Slot(str)
    def _on_driver_scan_error(self, err_msg: str):
        """驱动扫描异常回调"""
        self._scan_anim_page.stop()
        self._lock_ui(False)
        self._on_nav_clicked(self._btn_nav_install)
        self._statusbar.showMessage(f"扫描异常: {err_msg}")
        QMessageBox.critical(self, "扫描异常", f"分析驱动文件夹时出错：\n{err_msg}")
        logger.error(f"驱动扫描工作线程报错: {err_msg}")

    def _try_cross_match(self):
        devices = self._hardware_status.get_devices()
        if devices and self._drivers:
            from core.hardware_scanner import cross_match
            updated_devices = cross_match(devices, self._drivers)
            self._hardware_status.update_match_results(updated_devices)

    @Slot()
    def _on_hardware_scan_started(self):
        for btn in self._nav_group:
            btn.setChecked(False)
        self._stack.setCurrentIndex(5)  # 页面 5: 动画过渡页
        self._scan_anim_page.start("探测系统硬件...")
        self._lock_ui(True)

    @Slot(list)
    def _on_hardware_scan_completed(self, devices: list):
        self._try_cross_match()
        # 切回硬件界面
        self._on_nav_clicked(self._btn_nav_hardware)
        self._scan_anim_page.stop()
        self._lock_ui(False)

    @Slot(str)
    def _on_fix_requested(self, device_name: str):
        """响应硬件状态页的‘立即修复’，跳转并搜索"""
        # 1. 切换到驱动安装页
        self._on_nav_clicked(self._btn_nav_install)
        # 2. 在驱动列表中设置搜索过滤
        self._driver_list.set_filter_text(device_name)
        self._statusbar.showMessage(f"已为您筛选与 '{device_name}' 相关的驱动程序", 5000)

    @Slot()
    def _on_start_install(self):
        drivers = self._driver_list.get_drivers()
        enabled_count = sum(1 for d in drivers if d.enabled)
        if enabled_count == 0:
            QMessageBox.warning(self, "提示", "请选择要安装的驱动。")
            return
        
        self._drivers = drivers
        self._lock_ui(True)
        self._install_manager.set_signature_check_enabled(self._check_signature.isChecked())
        self._install_manager.set_drivers(self._drivers, self._resume_start_index)
        self._resume_start_index = 0
        self._install_manager.start()

    @Slot()
    def _on_cancel_install(self):
        if QMessageBox.question(self, "确认", "确定取消安装？") == QMessageBox.StandardButton.Yes:
            self._install_manager.cancel()
            self._lock_ui(False)
            self._progress_panel.set_status("安装已取消", "#FF9800")

    def _lock_ui(self, locked: bool):
        """锁定/解锁所有交互控件（驱动安装期间）"""
        self._driver_list.set_interactive(not locked)
        
        # 锁定顶部 Header 控件
        self._top_brand_combo.setEnabled(not locked)
        self._top_check_recursive.setEnabled(not locked)
        self._check_signature.setEnabled(not locked)
        self._btn_top_folder.setEnabled(not locked)
        
        self._progress_panel.set_installing(locked)
        self._sidebar.setEnabled(not locked)

    def _lock_sw_ui(self, locked: bool):
        """锁定/解锁软件安装相关控件"""
        self._software_list.set_interactive(not locked)
        self._btn_sw_folder.setEnabled(not locked)
        self._btn_sw_start.setEnabled(not locked)
        self._sw_progress_panel.set_installing(locked)
        self._sidebar.setEnabled(not locked)

    @Slot(int, int, DriverInfo)
    def _on_progress_updated(self, current: int, total: int, driver: DriverInfo):
        self._progress_panel.update_progress(current, total, driver.name)
        self._driver_list.update_driver_status(driver, "⏳ 安装中...")
        self._progress_panel.append_log(f"[{current}/{total}] 正在安装: {driver.name}")

    @Slot(DriverInfo, bool, str)
    def _on_install_finished(self, driver: DriverInfo, success: bool, message: str):
        status = "✅ 成功" if success else "❌ 失败"
        self._driver_list.update_driver_status(driver, status)
        self._progress_panel.append_log(f"  {status} {driver.name}: {message}")

    @Slot(DriverInfo, list)
    def _on_reboot_required(self, driver: DriverInfo, completed: list):
        try:
            current_index = next(
                index + 1 for index, item in enumerate(self._drivers) if item is driver
            )
        except StopIteration:
            current_index = min(len(completed), len(self._drivers))

        self._session_manager.save_session(
            self._drivers,
            current_index,
            self._current_folder,
            self._current_brand,
        )
        self._lock_ui(False)
        self._progress_panel.set_status("等待重启后继续", "#FF9800")

        reply = QMessageBox.question(
            self,
            "需要重启",
            f"{driver.name} 安装完成，需要重启电脑后继续剩余任务。现在重启吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                subprocess.Popen(
                    ["shutdown", "/r", "/t", "0"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except OSError as error:
                logger.error(f"发起系统重启失败: {error}")
                QMessageBox.critical(self, "重启失败", f"无法自动重启，请手动重启电脑。\n{error}")

    @Slot()
    def _on_install_cancelled(self):
        self._lock_ui(False)
        self._progress_panel.set_status("安装已取消", "#FF9800")

    @Slot(list)
    def _on_all_completed(self, drivers: list):
        self._session_manager.clear_session()
        self._lock_ui(False)
        self._progress_panel.set_status("任务完成", "#4CAF50")
        QMessageBox.information(self, "完成", "所有驱动安装任务已执行完毕。")

    def restore_session(self, session_data: dict):
        """恢复会话"""
        drivers, start_index = self._session_manager.restore_drivers(session_data)
        self._current_folder = session_data.get("driver_folder", "")
        self._current_brand = session_data.get("brand", "通用")
        self._top_brand_combo.setCurrentText(self._current_brand)
        self._drivers = drivers
        self._resume_start_index = start_index

        self._driver_list.set_drivers(self._drivers)

        for i, driver in enumerate(self._drivers):
            if i < start_index:
                status = "✅ 已完成" if driver.status != InstallStatus.FAILED else "❌ 已失败"
                self._driver_list.update_driver_status(driver, status)

        self._on_nav_clicked(self._btn_nav_install)
        self._on_start_install()
        logger.info(f"会话已恢复并继续安装")

    # ══════════════════════════════════════════════════════
    #  软件安装页面构建
    # ══════════════════════════════════════════════════════

    def _build_software_page(self) -> QWidget:
        """构建软件安装页面布局"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # ── Header: 标题 + 文件夹选择 ────────────────────────
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(0, 0, 0, 15)

        title_col = QVBoxLayout()
        sw_title = QLabel("软件安装助手")
        sw_title.setStyleSheet(f"font-size: 26px; font-weight: 800; color: {COLOR_ON_SURFACE}; font-family: {FONT_FAMILY_TITLE};")
        self._sw_subtitle = QLabel("请选择包含安装包的文件夹")
        self._sw_subtitle.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 13px; margin-top: 2px;")
        title_col.addWidget(sw_title)
        title_col.addWidget(self._sw_subtitle)
        h_layout.addLayout(title_col)
        h_layout.addStretch()

        # 统计摘要栏
        self._sw_stats_label = QLabel()
        self._sw_stats_label.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 12px; padding: 4px 12px; "
                                           f"background: #f1f4f8; border-radius: 12px;")
        self._sw_stats_label.setVisible(False)
        h_layout.addWidget(self._sw_stats_label)
        h_layout.addSpacing(12)

        # 选择文件夹按鈕
        self._btn_sw_folder = QPushButton(" 选择文件夹 ")
        self._btn_sw_folder.setObjectName("primary_button")
        self._btn_sw_folder.setFixedHeight(40)
        self._btn_sw_folder.setMinimumWidth(120)
        self._btn_sw_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_sw_folder.clicked.connect(self._on_sw_browse_folder)
        h_layout.addWidget(self._btn_sw_folder)

        # 路径面包屑
        self._lbl_sw_path = QLabel(" 未选择路径 ")
        self._lbl_sw_path.setStyleSheet(f"background-color: #f1f4f8; color: #7a869a; border-radius: 17px; "
                                        f"padding: 0 15px; font-size: 12px; font-family: {FONT_FAMILY_MONO};")
        self._lbl_sw_path.setMinimumWidth(150)
        h_layout.addWidget(self._lbl_sw_path)
        h_layout.addSpacing(16)

        # 加载与保存方案按钮
        self._btn_sw_load_preset = QPushButton("📂加载方案")
        self._btn_sw_load_preset.setStyleSheet(f"background: #fff; color: {COLOR_ON_SURFACE}; border: 1px solid #dcdcdc; border-radius: 6px; padding: 0 16px; font-weight: bold;")
        self._btn_sw_load_preset.setMinimumHeight(38)
        self._btn_sw_load_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_sw_load_preset.clicked.connect(self._on_sw_load_preset)
        h_layout.addWidget(self._btn_sw_load_preset)

        self._btn_sw_save_preset = QPushButton("💾保存方案")
        self._btn_sw_save_preset.setStyleSheet(f"background: #fff; color: {COLOR_ON_SURFACE}; border: 1px solid #dcdcdc; border-radius: 6px; padding: 0 16px; font-weight: bold;")
        self._btn_sw_save_preset.setMinimumHeight(38)
        self._btn_sw_save_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_sw_save_preset.clicked.connect(self._on_sw_save_preset)
        self._btn_sw_save_preset.setEnabled(False)
        h_layout.addWidget(self._btn_sw_save_preset)

        layout.addWidget(header)

        # ── 软件包列表 (带扫描动画) ──────────────────────────
        self._sw_stack = QStackedWidget()
        
        # 扫描动画页 (index 0)
        self._sw_scan_anim = ScanAnimationWidget()
        self._sw_stack.addWidget(self._sw_scan_anim)
        
        # 列表页 (index 1)
        self._software_list = SoftwareListWidget()
        self._software_list.package_edit_requested.connect(self._on_sw_edit_args)
        self._software_list.package_retry_requested.connect(self._on_sw_retry)
        self._sw_stack.addWidget(self._software_list)
        
        self._sw_stack.setCurrentIndex(1) # 默认显示列表（空态）
        layout.addWidget(self._sw_stack, 1)

        # ── 进度面板 ──────────────────────────────────
        self._sw_progress_panel = ProgressWidget()
        self._sw_progress_panel.start_clicked.connect(self._on_sw_start_install)
        self._sw_progress_panel.pause_clicked.connect(self._software_installer.pause)
        self._sw_progress_panel.resume_clicked.connect(self._software_installer.resume)
        self._sw_progress_panel.cancel_clicked.connect(self._on_sw_cancel)
        if hasattr(self._sw_progress_panel, '_btn_start'):
            self._sw_progress_panel._btn_start.setText("▶ 开始安装软件")
            self._btn_sw_start = self._sw_progress_panel._btn_start  # 共用指针以保持兼容
            self._btn_sw_start.setEnabled(False)

        layout.addWidget(self._sw_progress_panel)

        return page

    # ══════════════════════════════════════════════════════
    #  软件安装事件操作
    # ══════════════════════════════════════════════════════

    @Slot()
    def _on_sw_browse_folder(self):
        """选择安装包文件夹"""
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "选择包含安装包的文件夹")
        if folder:
            self._start_sw_scan(folder)

    def _start_sw_scan(self, folder: str):
        """启动异步扫描"""
        self._sw_folder = folder
        short = folder[:22] + "..." if len(folder) > 22 else folder
        self._lbl_sw_path.setText(f" {short} ")
        self._sw_subtitle.setText("正在扫描安装包…")
        self._btn_sw_folder.setEnabled(False)
        self._btn_sw_load_preset.setEnabled(False)
        self._btn_sw_save_preset.setEnabled(False)
        self._btn_sw_start.setEnabled(False)
        self._statusbar.showMessage(f"扫描软件包: {folder}...")

        # 开启扫描动画
        self._sw_stack.setCurrentIndex(0)
        self._sw_scan_anim.start("正在深度核验数字签名并分析安装包...")

        # 停止旸先前的扫描
        if self._sw_scan_worker and self._sw_scan_worker.isRunning():
            self._sw_scan_worker.cancel()
            self._sw_scan_worker.wait()

        self._sw_scan_worker = SoftwareScanWorker(folder, recursive=True)
        self._sw_scan_worker.scan_finished.connect(self._on_sw_scan_finished)
        self._sw_scan_worker.scan_error.connect(self._on_sw_scan_error)
        self._sw_scan_worker.start()

    @Slot(list)
    def _on_sw_scan_finished(self, packages: list):
        """扫描完成"""
        self._btn_sw_folder.setEnabled(True)
        self._btn_sw_load_preset.setEnabled(True)
        self._btn_sw_save_preset.setEnabled(True)
        self._sw_packages = packages
        
        # 停止动画并切换回列表
        self._sw_scan_anim.stop()
        self._sw_stack.setCurrentIndex(1)

        if not packages:
            self._sw_subtitle.setText("未在该文件夹中检测到安装包")
            self._sw_stats_label.setVisible(False)
            self._btn_sw_start.setEnabled(False)
            self._btn_sw_save_preset.setEnabled(False)
            QMessageBox.information(self, "未找到安装包",
                                    "该文件夹下未检测到 EXE / MSI / ZIP 安装包。")
            return

        # 检查是否需要还原预设配置
        if getattr(self, "_pending_preset", None):
            pr = self._pending_preset
            self._pending_preset = None
            for p_data in pr.get("packages", []):
                for pkg in packages:
                    if pkg.file_path == p_data.get("file_path"):
                        pkg.enabled = p_data.get("enabled", pkg.enabled)
                        pkg.user_override_args = p_data.get("user_override_args", pkg.user_override_args)
                        pkg.add_to_path = p_data.get("add_to_path", pkg.add_to_path)
                        pkg.create_shortcut = p_data.get("create_shortcut", pkg.create_shortcut)
                        break
            QMessageBox.information(self, "加载完毕", f"已应用装机方案配置。\n名称：{pr.get('name')}")

        self._software_list.set_packages(packages)
        self._btn_sw_start.setEnabled(True)
        self._sw_progress_panel.reset()

        # 更新统计摘要
        summary = self._software_list.get_summary()
        parts = [f"共 {summary['Total']} 个"]
        for k in ["EXE", "MSI", "ZIP", "Office", "ISO", "便携软件"]:
            if summary.get(k):
                parts.append(f"{k}: {summary[k]}")
        self._sw_stats_label.setText("  |  ".join(parts))
        self._sw_stats_label.setVisible(True)
        self._sw_subtitle.setText(f"检测到 {summary['Total']} 个安装包，点击“开始安装”即可批量安装")
        self._statusbar.showMessage(f"扫描完成：{summary['Total']} 个包")

    @Slot(str)
    def _on_sw_scan_error(self, msg: str):
        self._sw_scan_anim.stop()
        self._sw_stack.setCurrentIndex(1)
        self._btn_sw_folder.setEnabled(True)
        self._btn_sw_load_preset.setEnabled(True)
        self._statusbar.showMessage(f"扫描失败: {msg}")
        QMessageBox.critical(self, "扫描失败", msg)

    @Slot()
    def _on_sw_save_preset(self):
        from core.preset_manager import save_preset
        packages = self._software_list.get_packages()
        if not packages:
            return
        name, ok = QInputDialog.getText(self, "保存方案", "请输入装机方案名称（例如：行政办公室常用）：")
        if ok and name.strip():
            try:
                path = save_preset(name.strip(), self._sw_folder, packages)
                QMessageBox.information(self, "保存成功", f"方案已保存至：\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"无法保存方案：\n{e}")

    @Slot()
    def _on_sw_load_preset(self):
        from PySide6.QtWidgets import QFileDialog
        from core.preset_manager import load_preset
        import os
        
        data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
        file_path, _ = QFileDialog.getOpenFileName(self, "选择装机方案", data_dir, "JSON Files (*.json)")
        if not file_path:
            return
        try:
            data = load_preset(file_path)
            folder = data.get("folder", "")
            if not os.path.exists(folder):
                QMessageBox.warning(self, "路径不存在", f"方案绑定的文件夹已不存在：\n{folder}")
                return
            
            # 记录即将设置的预设，随后启动所在目录的扫描行为
            self._pending_preset = data
            self._start_sw_scan(folder)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法加载方案：\n{e}")

    @Slot()
    def _on_sw_start_install(self):
        """开始软件安装"""
        packages = self._software_list.get_packages()
        enabled = [p for p in packages if p.enabled]
        if not enabled:
            QMessageBox.warning(self, "提示", "请勾选至少一个安装包！")
            return

        self._sw_packages = packages
        self._lock_sw_ui(True)
        self._software_installer.set_signature_check_enabled(self._check_signature.isChecked())
        self._software_installer.set_packages(packages)
        self._software_installer.start()
        logger.info(f"开始安装 {len(enabled)} 个软件包")

    @Slot()
    def _on_sw_cancel(self):
        if QMessageBox.question(self, "确认", "确定取消软件安装？") == QMessageBox.StandardButton.Yes:
            self._software_installer.cancel()
            self._lock_sw_ui(False)
            self._sw_progress_panel.set_status("安装已取消", "#FF9800")

    @Slot()
    def _on_sw_cancelled(self):
        self._lock_sw_ui(False)
        self._sw_progress_panel.set_status("安装已取消", "#FF9800")

    @Slot(int, int, object)
    def _on_sw_progress_updated(self, current: int, total: int, pkg):
        self._sw_progress_panel.update_progress(current, total, pkg.name)
        self._software_list.update_package_status(pkg)
        self._sw_progress_panel.append_log(f"[{current}/{total}] 安装中: {pkg.name}")

    @Slot(object, bool, str)
    def _on_sw_install_finished(self, pkg, success: bool, message: str):
        self._software_list.update_package_status(pkg, pkg.error_message)
        status = "✅ 成功" if success else "❌ 失败"
        self._sw_progress_panel.append_log(f"  {status} {pkg.name}: {message}")

    @Slot(list)
    def _on_sw_all_completed(self, packages: list):
        self._lock_sw_ui(False)
        success = sum(1 for p in packages if p.status.value == "success")
        failed  = sum(1 for p in packages if p.status.value == "failed")
        self._sw_progress_panel.set_status(
            f"安装完成 ✔{success} ❌{failed}",
            "#4CAF50" if failed == 0 else "#F85149"
        )
        msg = f"全部安装完成！\n✅ 成功: {success} 个\n❌ 失败: {failed} 个"
        if failed:
            failed_names = [p.name for p in packages if p.status.value == "failed"]
            msg += "\n\n失败项目:\n" + "\n".join(f"  - {n}" for n in failed_names)
        QMessageBox.information(self, "软件安装完成", msg)
        logger.info(f"软件安装完成 —— 成功:{success} 失败:{failed}")

    @Slot(object)
    def _on_sw_edit_args(self, pkg):
        """弹框编辑安装参数"""
        from PySide6.QtWidgets import QInputDialog
        current = pkg.user_override_args or " ".join(pkg.silent_args)
        text, ok = QInputDialog.getText(
            self, f"编辑参数 — {pkg.name}",
            "输入自定义静默安装参数（覆盖自动检测结果）:",
            text=current
        )
        if ok:
            pkg.user_override_args = text.strip()
            logger.info(f"用户覆盖参数: {pkg.name} → {text}")

    @Slot(object)
    def _on_sw_retry(self, pkg):
        """[暂不支持单包重试，提示用户重新全部运行]"""
        QMessageBox.information(
            self, "重试提示",
            f"如需重试 {pkg.name}，请勾选它后重新点击“开始安装”。"
        )


    def closeEvent(self, event):
        """
        主窗口关闭生命周期管理 - 性能优化版
        
        优化策略：
        1. 首先向所有活动线程批量发送停止/取消信号，不进行即时等待
        2. 统一调用 quit() 告知线程进入退出流程
        3. 遍历检查各线程状态，设置较短的阻塞阈值 (500ms)
        """
        logger.info("主窗口正在关闭，启动高性能后台任务清理流程...")
        
        # ── 1. 批量收集并先行发出停止信号 ──
        workers = []
        
        # 仪表盘监控
        if hasattr(self, '_dashboard') and self._dashboard:
            self._dashboard.stop_monitoring()

        if hasattr(self, '_system_specs') and self._system_specs:
            self._system_specs.stop()
            
        # 核心任务管理器
        cleanup_attrs = ['_install_manager', '_software_installer', '_sw_scan_worker', '_driver_scan_worker']
        for attr in cleanup_attrs:
            w = getattr(self, attr, None)
            if w and w.isRunning():
                if hasattr(w, 'cancel'): w.cancel()
                w.quit()
                workers.append((attr, w))

        # ── 2. 并行化等待策略 ──
        # 给这些线程一个极短的窗口时间来响应 quit()，避免累积阻塞
        for name, worker in workers:
            try:
                # 针对不同性质的线程给予不同的柔性宽限期
                timeout = 800 if 'installer' in name else 400
                if not worker.wait(timeout):
                    logger.warning(f"线程 {name} 在 {timeout}ms 内未响应退出，强制跳过并允许进程终结")
            except Exception as e:
                logger.error(f"清理线程 {name} 时发生异常: {e}")

        logger.info("后台清理流程执行完成，程序退出")
        super().closeEvent(event)
