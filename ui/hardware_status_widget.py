# -*- coding: utf-8 -*-
"""
硬件状态 Tab 组件

显示系统硬件设备列表及驱动状态，支持：
- 设备列表（状态图标 + 设备名 + 类别 + 制造商 + 驱动版本 + 匹配结果）
- 一键扫描按钮
- 状态统计摘要
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QFrame, QSizePolicy, QCheckBox
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QColor, QBrush, QFont

from models.device_info import DeviceInfo, DeviceStatus, MatchStatus, IssueLevel
from utils.logger import get_logger

logger = get_logger("HardwareStatusWidget")


class _ScanWorker(QThread):
    """硬件扫描工作线程"""
    scan_finished = Signal(list)  # list[DeviceInfo]
    scan_error = Signal(str)

    def run(self):
        try:
            from core.hardware_scanner import scan_hardware
            devices = scan_hardware()
            self.scan_finished.emit(devices)
        except Exception as e:
            self.scan_error.emit(str(e))


from ui.styles import (
    COLOR_ON_SURFACE_VARIANT, COLOR_WHITE, COLOR_PRIMARY, COLOR_ON_SURFACE, COLOR_SURFACE_CONTAINER, FONT_FAMILY_TITLE
)

class HardwareStatusWidget(QWidget):
    """
    硬件状态面板 - Ethereal Asymmetric Layout
    """

    scan_completed = Signal(list)
    scan_started = Signal()
    fix_requested = Signal(str) # 传递设备名或硬件ID用于搜索

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: list[DeviceInfo] = []
        self._show_all = False
        self._scan_worker: _ScanWorker | None = None
        self._setup_ui()

    def _setup_ui(self):
        """初始化非对称布局"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(30)

        # === 左侧：英雄卡片与操作区 (1/3 宽度) ===
        left_panel = QVBoxLayout()
        left_panel.setSpacing(20)

        # 健康报告及结论区 (Narrative Area)
        self._report_icon = QLabel("🔍")
        self._report_icon.setStyleSheet("font-size: 48px; margin-top: 20px;")
        self._report_icon.setAlignment(Qt.AlignmentFlag.AlignLeft)
        left_panel.addWidget(self._report_icon)

        self._narrative_lbl = QLabel("正在分析系统硬件...")
        self._narrative_lbl.setStyleSheet(f"font-size: 26px; font-weight: 900; color: {COLOR_ON_SURFACE}; font-family: {FONT_FAMILY_TITLE}; line-height: 1.3;")
        self._narrative_lbl.setWordWrap(True)
        left_panel.addWidget(self._narrative_lbl)

        self._sub_narrative_lbl = QLabel("请稍候，我们正在为您核对驱动健康度")
        self._sub_narrative_lbl.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 14px; font-weight: 500;")
        self._sub_narrative_lbl.setWordWrap(True)
        left_panel.addWidget(self._sub_narrative_lbl)

        left_panel.addSpacing(20)

        # 扫描按钮
        self._btn_scan = QPushButton("重新扫描系统硬件")
        self._btn_scan.setObjectName("primary_button")
        self._btn_scan.setFixedHeight(50)
        self._btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_scan.clicked.connect(self._on_scan)
        left_panel.addWidget(self._btn_scan)

        # 状态切换
        self._chk_show_all = QCheckBox("显示全部设备节点")
        self._chk_show_all.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 13px; margin-top: 10px;")
        self._chk_show_all.toggled.connect(self._on_toggle_show_all)
        left_panel.addWidget(self._chk_show_all)

        left_panel.addStretch(1)
        layout.addLayout(left_panel, 1)

        # === 右侧：详细内容区 (2/3 宽度) ===
        right_panel = QVBoxLayout()
        right_panel.setSpacing(20)

        # 状态统计微卡片
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(10)
        
        self._lbl_missing = QLabel("⚠️ 缺失: —")
        self._lbl_generic = QLabel("🔶 通用: —")
        self._lbl_matched = QLabel("✅ 匹配: —")
        
        for lbl in [self._lbl_missing, self._lbl_generic, self._lbl_matched]:
            lbl.setObjectName("stat_label")
            stats_layout.addWidget(lbl)
        
        stats_layout.addStretch()
        right_panel.addLayout(stats_layout)

        # 滚动列表容纳卡片
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background-color: transparent;")
        
        self._list_container = QWidget()
        self._list_container.setStyleSheet("background-color: transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setSpacing(16)
        self._list_layout.setContentsMargins(0, 0, 10, 0)
        
        self._scroll.setWidget(self._list_container)
        right_panel.addWidget(self._scroll, 1)
        
        layout.addLayout(right_panel, 2)

    def _on_scan(self):
        self._btn_scan.setEnabled(False)
        self._btn_scan.setText("正在分析系统...")
        self.scan_started.emit()
        self._scan_worker = _ScanWorker()
        self._scan_worker.scan_finished.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_finished(self, devices: list[DeviceInfo]):
        self._devices = devices
        self._refresh_list()
        self._update_narrative() # 升级版摘要逻辑
        self._btn_scan.setEnabled(True)
        self._btn_scan.setText("重新扫描系统硬件")
        self.scan_completed.emit(devices)

    def _on_toggle_show_all(self, checked):
        self._show_all = checked
        self._refresh_list()

    def _create_section_header(self, text: str, count: int, color: str = COLOR_ON_SURFACE_VARIANT):
        """创建带计数的的分组标题"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(5, 10, 5, 0)
        
        lbl = QLabel(f"{text} ({count})")
        lbl.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {color}; font-family: {FONT_FAMILY_TITLE};")
        layout.addWidget(lbl)
        layout.addStretch()
        return container

    def _refresh_list(self):
        # 清空旧卡片
        while self._list_layout.count():
            child = self._list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
        if not self._devices:
            return

        # 1. 分类设备
        attention_needed = [d for d in self._devices if d.issue_level in (IssueLevel.CRITICAL, IssueLevel.WARNING)]
        healthy_devices = [d for d in self._devices if d.issue_level == IssueLevel.INFO]
        
        # 2. 渲染“需处理”部分
        if attention_needed:
            self._list_layout.addWidget(self._create_section_header("🚨 建议立即处理", len(attention_needed), "#E53935"))
            for dev in sorted(attention_needed, key=lambda x: x.issue_level != IssueLevel.CRITICAL):
                self._add_device_card(dev)
        
        # 3. 渲染“正常”部分 (受控制)
        if healthy_devices:
            if self._show_all or not attention_needed:
                self._list_layout.addWidget(self._create_section_header("✅ 运行正常的设备", len(healthy_devices)))
                # 进一步过滤掉特别琐碎的设备，除非用户强行查看全部且没有待处理项
                visible_healthy = healthy_devices
                if not self._show_all:
                    visible_healthy = [d for d in healthy_devices if not d.is_filtered]
                
                for dev in sorted(visible_healthy, key=lambda x: x.class_display_name):
                    self._add_device_card(dev)
        
        if not attention_needed and not healthy_devices:
            # 空状态占位
            empty_lbl = QLabel("✨ 您的硬件状态极佳，未发现明显驱动问题")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 16px; margin-top: 50px;")
            self._list_layout.addWidget(empty_lbl)
            
        self._list_layout.addStretch()

    def _add_device_card(self, dev: DeviceInfo):
        """内部方法：添加单个设备卡片"""
        card = QFrame()
        card.setObjectName("card")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        
        indicator = QFrame()
        indicator.setFixedSize(12, 12)
        if dev.issue_level == IssueLevel.CRITICAL:
            color = "#F44336" 
        elif dev.issue_level == IssueLevel.WARNING:
            color = "#FFC107" 
        else:
            color = "#4CAF50" 
        indicator.setStyleSheet(f"background-color: {color}; border-radius: 6px;")
        card_layout.addWidget(indicator)
        
        content_layout = QVBoxLayout()
        content_layout.setSpacing(4)
        
        name_row = QHBoxLayout()
        title = QLabel(dev.name)
        title.setStyleSheet(f"font-weight: 800; font-size: 16px; color: {COLOR_ON_SURFACE};")
        name_row.addWidget(title)
        name_row.addStretch()
        content_layout.addLayout(name_row)
        
        status_desc = QLabel(dev.human_readable_status)
        status_desc.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")
        content_layout.addWidget(status_desc)
        
        detail_text = f"{dev.class_display_name} • 当前版本: {dev.driver_version or '未知'}"
        if dev.matched_driver_name:
            detail_text += f" • 📦 源可用: {dev.matched_driver_name}"
        
        detail = QLabel(detail_text)
        detail.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 12px;")
        content_layout.addWidget(detail)
        
        card_layout.addLayout(content_layout, 1)
        
        if dev.issue_level in (IssueLevel.CRITICAL, IssueLevel.WARNING):
            btn_fix = QPushButton("立即修复")
            btn_fix.setObjectName("primary_button")
            # 按钮配色区分级别
            bg_color = "#f44336" if dev.issue_level == IssueLevel.CRITICAL else "#007bff"
            btn_fix.setStyleSheet(f"background: {bg_color}; border-radius: 17px; height: 34px; padding: 0 20px;")
            btn_fix.setFixedWidth(100)
            btn_fix.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_fix.clicked.connect(lambda _, d=dev: self.fix_requested.emit(d.name))
            card_layout.addWidget(btn_fix)
        
        self._list_layout.addWidget(card)

    def _update_narrative(self):
        """升级版：叙事型状态更新"""
        total = len(self._devices)
        if total == 0: return
        
        critical_count = sum(1 for d in self._devices if d.issue_level == IssueLevel.CRITICAL)
        warning_count  = sum(1 for d in self._devices if d.issue_level == IssueLevel.WARNING)
        
        if critical_count > 0:
            self._report_icon.setText("🚨")
            self._narrative_lbl.setText(f"发现 {critical_count} 个严重硬件故障")
            self._narrative_lbl.setStyleSheet(f"font-size: 26px; font-weight: 900; color: #E53935; font-family: {FONT_FAMILY_TITLE};")
            self._sub_narrative_lbl.setText("部分核心驱动缺失，设备无法正常工作，建议优先安装修复。")
            self._lbl_missing.setStyleSheet("color: #F44336; font-weight: bold;")
        elif warning_count > 0:
            self._report_icon.setText("🔶")
            self._narrative_lbl.setText(f"有 {warning_count} 个设备可以运行得更好")
            self._narrative_lbl.setStyleSheet(f"font-size: 26px; font-weight: 900; color: #FF9800; font-family: {FONT_FAMILY_TITLE};")
            self._sub_narrative_lbl.setText("当前正在使用系统通用驱动，建议安装专用驱动以释放硬件全部性能。")
            self._lbl_generic.setStyleSheet("color: #FF9800; font-weight: bold;")
        else:
            self._report_icon.setText("✨")
            self._narrative_lbl.setText("硬件状态极佳")
            self._narrative_lbl.setStyleSheet(f"font-size: 26px; font-weight: 900; color: #4CAF50; font-family: {FONT_FAMILY_TITLE};")
            self._sub_narrative_lbl.setText(f"已检测到 {total} 个节点，所有核心设备均已匹配最优驱动。")
            self._lbl_matched.setStyleSheet("color: #4CAF50; font-weight: bold;")

        # 同步底部小统计提示
        self._lbl_missing.setText(f"缺失: {critical_count}")
        self._lbl_generic.setText(f"通用: {warning_count}")
        self._lbl_matched.setText(f"正常: {total - critical_count - warning_count}")

    def get_devices(self) -> list[DeviceInfo]:
        return list(self._devices)

    def update_match_results(self, devices: list[DeviceInfo]):
        self._devices = devices
        self._refresh_list()
        self._update_narrative()
