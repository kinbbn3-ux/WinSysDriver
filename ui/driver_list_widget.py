# -*- coding: utf-8 -*-
"""
驱动列表组件 - 3.0 精英增强版
包含安装优先级序号、圆形选框、置信度徽章等。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QAbstractItemView, QLabel, QSizePolicy, QLineEdit
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPen

from models.driver_info import DriverInfo
from ui.styles import (
    COLOR_ON_SURFACE_VARIANT, COLOR_WHITE, COLOR_PILL_BG, COLOR_PRIMARY, COLOR_GRAY_TEXT, COLOR_ON_SURFACE, COLOR_BADGE_BG, COLOR_BADGE_TEXT, FONT_FAMILY_TITLE
)

class RoundCheckBoxWithNumber(QWidget):
    """带序号的圆形勾选框，解决用户对安装顺序的直观展示需求"""
    toggled = Signal(bool)
    
    def __init__(self, number, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 24)
        self._number = number
        self._checked = checked
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def setChecked(self, checked):
        self._checked = checked
        self.update()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.toggled.emit(self._checked)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 1. 画数字 (优先级)
        painter.setPen(QColor(COLOR_GRAY_TEXT))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.drawText(0, 0, 18, 24, Qt.AlignmentFlag.AlignCenter, str(self._number))
        
        # 2. 画圆圈勾选框
        rect = self.rect().adjusted(22, 2, -2, -2)
        if self._checked:
            painter.setBrush(QColor(COLOR_PRIMARY))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(rect)
            
            painter.setPen(QPen(QColor(COLOR_WHITE), 2))
            painter.drawLine(rect.center().x() - 4, rect.center().y(), rect.center().x() - 1, rect.center().y() + 3)
            painter.drawLine(rect.center().x() - 1, rect.center().y() + 3, rect.center().x() + 5, rect.center().y() - 3)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#D1D9E6"), 2))
            painter.drawEllipse(rect)

class DriverListWidget(QWidget):
    """
    驱动列表组件 - 3.0 版
    """
    drivers_changed = Signal()

    COL_PRIORITY = 0
    COL_NAME = 1
    COL_VENDOR = 2
    COL_CATEGORY = 3
    COL_VERSION = 4
    COL_STATUS = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drivers: list[DriverInfo] = []
        self._filter_text = ""
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 顶部头部容器
        header_container = QWidget()
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(15, 5, 15, 5)
        
        list_title = QLabel("待安装驱动队列")
        list_title.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {COLOR_ON_SURFACE}; font-family: {FONT_FAMILY_TITLE};")
        header_layout.addWidget(list_title)
        
        # 搜索框 (NEW)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍 搜索驱动名称及关键词...")
        self._search_edit.setFixedWidth(240)
        self._search_edit.setStyleSheet(f"""
            background-color: {COLOR_WHITE};
            border: 1px solid #D1D9E6;
            border-radius: 14px;
            padding: 4px 12px;
            font-size: 13px;
        """)
        self._search_edit.textChanged.connect(self._on_search_changed)
        header_layout.addWidget(self._search_edit)

        header_layout.addStretch()
        
        self._count_badge = QLabel("已锁定顺序: 0 项")
        self._count_badge.setStyleSheet(f"""
            background-color: {COLOR_BADGE_BG}; 
            color: {COLOR_BADGE_TEXT}; 
            border-radius: 12px; 
            padding: 4px 14px; 
            font-weight: 700; 
            font-size: 11px;
        """)
        header_layout.addWidget(self._count_badge)
        layout.addWidget(header_container)

        # TreeWidget
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels([" ", "名称", "制造商", "类别", "版本", "当前状态"])
        self._tree.setRootIsDecorated(False)
        self._tree.setIndentation(0)
        
        header = self._tree.header()
        header.setStretchLastSection(False)
        header.resizeSection(0, 80) # 优先级+勾选
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(2, 160)
        header.resizeSection(3, 130)
        header.resizeSection(4, 130)
        header.resizeSection(5, 100)

        layout.addWidget(self._tree)

    def set_drivers(self, drivers: list[DriverInfo]):
        self._drivers = drivers
        self._refresh_list()
        self.update_count()

    def get_drivers(self) -> list[DriverInfo]:
        return list(self._drivers)

    def set_filter_text(self, text: str):
        """设置过滤文本（用于跨页面联动修复）"""
        self._search_edit.setText(text)
        self._filter_text = text.lower()
        self._refresh_list()

    def update_count(self):
        enabled_count = sum(1 for d in self._drivers if d.enabled)
        self._count_badge.setText(f"已选 {enabled_count} 项")

    def _on_search_changed(self, text):
        self._filter_text = text.lower()
        self._refresh_list()

    def _refresh_list(self):
        self._tree.clear()
        
        # 应用过滤
        display_drivers = self._drivers
        if self._filter_text:
            display_drivers = [
                d for d in display_drivers 
                if self._filter_text in d.name.lower() or 
                   self._filter_text in d.vendor.lower() or
                   self._filter_text in d.category.value.lower()
            ]

        for i, driver in enumerate(display_drivers):
            item = QTreeWidgetItem()
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            
            # 设置基本列
            item.setText(self.COL_NAME, driver.name)
            font = item.font(self.COL_NAME)
            font.setBold(True)
            font.setPointSize(11)
            item.setFont(self.COL_NAME, font)
            
            item.setText(self.COL_VENDOR, driver.vendor)
            item.setForeground(self.COL_VENDOR, QBrush(QColor(COLOR_GRAY_TEXT)))
            
            version_text = getattr(driver, 'version', "546.17-whq1")
            item.setText(self.COL_VERSION, version_text)
            item.setForeground(self.COL_VERSION, QBrush(QColor(COLOR_GRAY_TEXT)))
            
            self._tree.addTopLevelItem(item)

            # 注入自定义控件
            # 1. 优先级及圆形勾选
            chk_with_num = RoundCheckBoxWithNumber(i + 1, driver.enabled)
            chk_with_num.toggled.connect(lambda state, d=driver: self._on_toggled(d, state))
            
            container = QWidget()
            c_layout = QHBoxLayout(container)
            c_layout.setContentsMargins(10, 0, 0, 0)
            c_layout.addWidget(chk_with_num)
            self._tree.setItemWidget(item, self.COL_PRIORITY, container)
            
            # 2. 类别药丸
            pill_cnt = QWidget()
            pill_layout = QHBoxLayout(pill_cnt)
            pill_layout.setContentsMargins(0, 0, 0, 0)
            cat_lbl = QLabel(driver.category.value)
            cat_lbl.setStyleSheet(f"background-color: {COLOR_PILL_BG}; color: #7a869a; border-radius: 10px; padding: 2px 10px; font-size: 11px;")
            pill_layout.addWidget(cat_lbl)
            pill_layout.addStretch()
            self._tree.setItemWidget(item, self.COL_CATEGORY, pill_cnt)
            
            # 3. 状态标签
            status_lbl = QLabel("等待执行...")
            status_lbl.setStyleSheet("color: #4c84ff; font-weight: bold; font-size: 12px;")
            self._tree.setItemWidget(item, self.COL_STATUS, status_lbl)

    def _on_toggled(self, driver, state):
        driver.enabled = state
        self.update_count()
        self.drivers_changed.emit()

    def update_driver_status(self, driver: DriverInfo, status_text: str):
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            idx = item.data(0, Qt.ItemDataRole.UserRole)
            if idx is not None and self._drivers[idx] is driver:
                lbl = self._tree.itemWidget(item, self.COL_STATUS)
                if lbl:
                    lbl.setText(status_text)
                    if any(x in status_text for x in ["✅", "成功"]):
                        lbl.setStyleSheet("color: #4CAF50; font-weight: bold;")
                    elif "安装中" in status_text:
                        lbl.setStyleSheet("color: #FFC107; font-weight: bold;")
                    elif "❌" in status_text:
                        lbl.setStyleSheet("color: #F44336; font-weight: bold;")
                break

    def set_interactive(self, enabled: bool):
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            cnt = self._tree.itemWidget(item, self.COL_PRIORITY)
            if cnt:
                cnt.findChild(RoundCheckBoxWithNumber).setEnabled(enabled)
