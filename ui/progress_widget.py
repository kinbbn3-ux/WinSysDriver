# -*- coding: utf-8 -*-
"""
安装进度面板组件 - 日志内嵌版
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QProgressBar,
    QLabel, QPushButton, QFrame, QSizePolicy, QPlainTextEdit
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QIcon, QPainter, QColor

from ui.styles import (
    COLOR_ON_SURFACE_VARIANT, COLOR_WHITE, COLOR_PRIMARY_VARIANT, COLOR_PRIMARY, COLOR_GRAY_TEXT, COLOR_ON_SURFACE, COLOR_SURFACE_CONTAINER, FONT_FAMILY_MONO
)

class ProgressWidget(QWidget):
    """
    底部进度控制栏 - 深度还原设计图，并内嵌 Terminal 风格折叠日志
    """

    start_clicked = Signal()
    pause_clicked = Signal()
    resume_clicked = Signal()
    cancel_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_running = False
        self._is_paused = False
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 上半部分：Terminal 日志面板（默认隐藏） ──
        self._log_container = QFrame(self)
        self._log_container.setFixedHeight(200)
        self._log_container.setVisible(False)
        self._log_container.setStyleSheet(f"""
            QFrame {{
                background-color: #1a1b22; 
                border-top: 1px solid {COLOR_SURFACE_CONTAINER};
            }}
        """)
        
        log_layout = QVBoxLayout(self._log_container)
        log_layout.setContentsMargins(40, 15, 40, 15)
        
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet(f"""
            QPlainTextEdit {{
                color: #c9d1d9; 
                font-family: {FONT_FAMILY_MONO}; 
                font-size: 13px; 
                border: none; 
                background: transparent;
            }}
        """)
        log_layout.addWidget(self._log_view)
        
        # 将日志面板添加到主垂直布局
        main_layout.addWidget(self._log_container)

        # ── 下半部分：进度与操作按钮 ──
        self.main_container = QFrame(self)
        self.main_container.setFixedHeight(100)
        
        container_layout = QHBoxLayout(self.main_container)
        container_layout.setContentsMargins(40, 0, 40, 0)
        container_layout.setSpacing(30)

        # 1. 左侧用户信息 (系统管理员)
        user_layout = QHBoxLayout()
        user_avatar = QLabel()
        user_avatar.setFixedSize(40, 40)
        user_avatar.setStyleSheet(f"background-color: #3e4a5b; border-radius: 20px;") # 模拟头像
        
        user_info = QVBoxLayout()
        user_name = QLabel("系统管理员")
        user_name.setStyleSheet(f"color: {COLOR_ON_SURFACE}; font-weight: bold; font-size: 13px;")
        user_role = QLabel("高级工程师")
        user_role.setStyleSheet(f"color: {COLOR_GRAY_TEXT}; font-size: 11px;")
        user_info.addWidget(user_name)
        user_info.addWidget(user_role)
        user_info.setSpacing(0)
        
        user_layout.addWidget(user_avatar)
        user_layout.addLayout(user_info)
        container_layout.addLayout(user_layout)

        # 2. 中间进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLOR_SURFACE_CONTAINER};
                border-radius: 4px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: #4c84ff;
                border-radius: 4px;
            }}
        """)
        self._status_label = QLabel("待命")
        self._status_label.setMinimumWidth(110)
        self._status_label.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 12px; font-weight: bold;")
        container_layout.addWidget(self._status_label)
        container_layout.addWidget(self._progress_bar, 1)

        # 3. 操作按钮
        self._btn_log = QPushButton("📋 日志")
        self._btn_log.setStyleSheet(f"color: {COLOR_PRIMARY}; font-weight: bold; background: transparent; padding: 5px;")
        self._btn_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_log.clicked.connect(self._toggle_log)
        container_layout.addWidget(self._btn_log)

        self._btn_pause = QPushButton("暂停")
        self._btn_pause.setStyleSheet(f"color: {COLOR_GRAY_TEXT}; font-weight: bold; background: transparent;")
        self._btn_pause.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_pause.setEnabled(False)
        self._btn_pause.clicked.connect(self._on_pause_toggle)
        container_layout.addWidget(self._btn_pause)

        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.setStyleSheet(f"color: {COLOR_GRAY_TEXT}; font-weight: bold; background: transparent;")
        self._btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self.cancel_clicked.emit)
        container_layout.addWidget(self._btn_cancel)

        self._btn_start = QPushButton(" ▶  开始安装")
        self._btn_start.setObjectName("primary_button")
        self._btn_start.setFixedHeight(54)
        self._btn_start.setMinimumWidth(180)
        self._btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.clicked.connect(self.start_clicked.emit)
        container_layout.addWidget(self._btn_start)

        main_layout.addWidget(self.main_container)

    def _toggle_log(self):
        """折叠/展开日志面板"""
        self._log_container.setVisible(not self._log_container.isVisible())

    def _on_pause_toggle(self):
        if self._is_paused:
            self._is_paused = False
            self._btn_pause.setText("暂停")
            self.resume_clicked.emit()
        else:
            self._is_paused = True
            self._btn_pause.setText("恢复")
            self.pause_clicked.emit()

    def set_installing(self, is_installing: bool):
        self._is_running = is_installing
        self._btn_start.setEnabled(not is_installing)
        self._btn_pause.setEnabled(is_installing)
        self._btn_cancel.setEnabled(is_installing)
        if is_installing:
            self._is_paused = False
            self._btn_pause.setText("暂停")
            # 不自动展开日志，保持静默除非用户主动看

    def update_progress(self, current: int, total: int, driver_name: str):
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)

    def set_status(self, text: str, color: str = None):
        self._status_label.setText(text)
        if color:
            self._status_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")

    def append_log(self, message: str):
        """写入实时日志并自动滚动到底部"""
        self._log_view.appendPlainText(message)
        scrollbar = self._log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def reset(self):
        self._progress_bar.setValue(0)
        self._log_view.clear()
        self.set_installing(False)
