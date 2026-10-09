# -*- coding: utf-8 -*-
"""
深空扫描动画组件 (Scan Animation Widget)

显示一个科技感十足的“脉冲式”同心圆扫描动画。
用于在查找驱动和交叉分析硬件时展示。
"""

import math
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QFont

from ui.styles import COLOR_WHITE, COLOR_PRIMARY_VARIANT, COLOR_PRIMARY, FONT_FAMILY_TITLE, FONT_FAMILY_BODY

class PulseCircleWidget(QWidget):
    """自定义绘制的同心圆脉冲动画控件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        
        # 动画状态变量
        self._phase = 0.0
        
        # 定时器驱动动画重绘
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_animation)
        self._timer.setInterval(16)  # ~60fps
        
    def start_animation(self):
        self._timer.start()
        
    def stop_animation(self):
        self._timer.stop()
        
    def _update_animation(self):
        self._phase += 0.03
        if self._phase > 2 * math.pi:
            self._phase -= 2 * math.pi
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        center = rect.center()
        
        # 最大可用半径
        max_radius = min(rect.width(), rect.height()) / 2.0 - 10
        
        # 基础颜色
        base_color = QColor(COLOR_PRIMARY)
        
        # 绘制多个同心的扩散圆
        num_circles = 3
        for i in range(num_circles):
            # i 越小，向外扩散。计算当前的扩散半径和透明度
            # 利用相移让各个圆交错扩散
            offset_phase = (self._phase + i * (2 * math.pi / num_circles)) % (2 * math.pi)
            
            # 从 0 到 1 的扩散进度
            progress = offset_phase / (2 * math.pi)
            
            current_radius = max_radius * progress
            
            # 透明度随扩散衰减：中心最不透明，边缘透明度为0
            alpha = int(255 * (1.0 - progress) * 0.6)  # 最高约 60% 不透明度
            
            pen = QPen(base_color)
            pen.setWidth(2)
            c = base_color
            c.setAlpha(alpha)
            pen.setColor(c)
            
            painter.setPen(pen)
            
            # 不填充
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, current_radius, current_radius)
        
        # 绘制中心的一个实体亮色圆
        painter.setPen(Qt.PenStyle.NoPen)
        inner_color = QColor(COLOR_PRIMARY)
        inner_color.setAlpha(200)
        painter.setBrush(inner_color)
        painter.drawEllipse(center, max_radius * 0.15, max_radius * 0.15)
        
        # 绘制中心第二层高亮圆
        highlight = QColor(COLOR_WHITE)
        highlight.setAlpha(150)
        painter.setBrush(highlight)
        painter.drawEllipse(center, max_radius * 0.05, max_radius * 0.05)
        
        painter.end()


class ScanAnimationWidget(QWidget):
    """包装扫描动画及状态文字的组件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        
        self.pulse_widget = PulseCircleWidget()
        self.pulse_widget.setFixedSize(300, 300)
        layout.addWidget(self.pulse_widget, 0, Qt.AlignmentFlag.AlignHCenter)
        
        self.label = QLabel("正在深度分析系统硬件...")
        self.label.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 16px; font-weight: bold; font-family: {FONT_FAMILY_TITLE};")
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignHCenter)
        
        self.sub_label = QLabel("")
        self.sub_label.setStyleSheet(f"color: #8e8e93; font-size: 13px; font-family: {FONT_FAMILY_BODY};")
        layout.addWidget(self.sub_label, 0, Qt.AlignmentFlag.AlignHCenter)
        
    def start(self, title_text="正在分析...", sub_text=""):
        self.label.setText(title_text)
        self.sub_label.setText(sub_text)
        self.sub_label.setHidden(not sub_text)
        self.pulse_widget.start_animation()
        
    def stop(self):
        self.pulse_widget.stop_animation()
