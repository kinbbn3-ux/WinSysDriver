# -*- coding: utf-8 -*-
"""
Dashboard 仪表盘页面 - 4.0 设计图精准还原版
完整还原：CPU / RAM / GPU / 存储 / 散热 / 线程 六块监控卡片
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QGridLayout, QPushButton, QProgressBar, QSizePolicy, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush, QPainterPath

from ui.styles import (
    COLOR_ON_SURFACE_VARIANT, COLOR_WHITE, COLOR_PRIMARY_VARIANT, COLOR_PRIMARY, COLOR_GRAY_TEXT, COLOR_ON_SURFACE, FONT_FAMILY_TITLE
)

from core.monitoring_engine import MonitoringEngine, MonitorWorker

# ─────────────────────────────────────────────
#  自定义圆环仪表盘
# ─────────────────────────────────────────────
class CpuDonut(QWidget):
    """CPU 圆环表盘 – 仿设计图，显示数值+%+LOAD"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFixedSize(170, 170)
        self._value = 0

    def set_value(self, val: float):
        self._value = max(0, min(100, val))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = 18
        rect = QRectF(m, m, self.width() - m*2, self.height() - m*2)

        # 底色轨道
        pen = QPen(QColor("#eaecf4"), 13, Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen); p.drawEllipse(rect)

        # 进度弧（蓝紫渐变色用近似色代替）
        grad_color = QColor("#5b8cff")
        pen.setColor(grad_color)
        p.setPen(pen)
        span = int(-(self._value / 100.0) * 360 * 16)
        p.drawArc(rect, 90 * 16, span)

        cx, cy = self.width()/2, self.height()/2

        # 数值
        p.setPen(QColor(COLOR_ON_SURFACE))
        p.setFont(QFont("Manrope", 30, QFont.Weight.ExtraBold))
        fm = p.fontMetrics()
        val_str = str(int(self._value))
        p.drawText(cx - fm.horizontalAdvance(val_str)/2 - 8, cy + 8, val_str)

        # % 符号（右上偏）
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        fm2 = p.fontMetrics()
        p.setPen(QColor(COLOR_ON_SURFACE))
        p.drawText(cx + fm.horizontalAdvance(val_str)/2 - 6, cy - 2, "%")

        # LOAD 标注
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Black))
        p.setPen(QColor(COLOR_GRAY_TEXT))
        fm3 = p.fontMetrics()
        p.drawText(cx - fm3.horizontalAdvance("负载")/2, cy + 24, "负载")


class RamDonut(QWidget):
    """RAM 环形 – 显示已用 GB 而非百分比"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFixedSize(150, 150)
        self._pct = 0
        self._used_gb = 0.0

    def set_value(self, used_gb: float, total_gb: float):
        self._used_gb = used_gb
        self._pct = (used_gb / total_gb * 100) if total_gb > 0 else 0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = 14
        rect = QRectF(m, m, self.width()-m*2, self.height()-m*2)

        pen = QPen(QColor("#eaecf4"), 11)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen); p.drawEllipse(rect)

        pen.setColor(QColor("#7c5cfc"))
        p.setPen(pen)
        span = int(-(self._pct / 100.0) * 360 * 16)
        p.drawArc(rect, 90*16, span)

        cx, cy = self.width()/2, self.height()/2

        # 数值 "12.4"
        p.setPen(QColor(COLOR_ON_SURFACE))
        p.setFont(QFont("Manrope", 24, QFont.Weight.ExtraBold))
        fm = p.fontMetrics()
        num_str = f"{self._used_gb:.1f}"
        p.drawText(cx - fm.horizontalAdvance(num_str)/2 - 8, cy + 6, num_str)

        # "GB" 上标
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        fm2 = p.fontMetrics()
        p.drawText(cx + fm.horizontalAdvance(num_str)/2 - 7, cy - 6, "GB")

        # "USED"
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.Black))
        p.setPen(QColor(COLOR_GRAY_TEXT))
        fm3 = p.fontMetrics()
        p.drawText(cx - fm3.horizontalAdvance("已用")/2, cy + 22, "已用")


# ─────────────────────────────────────────────
#  通用卡片容器
# ─────────────────────────────────────────────
class Card(QFrame):
    """卡片容器 - 无阴影、无边框继承"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dashCard")
        self.setStyleSheet(
            "QFrame#dashCard {"
            f"  background: {COLOR_WHITE};"
            "  border-radius: 24px;"
            "  border: 1px solid #eaedf3;"
            "}"
            " QFrame#dashCard QLabel { border: none; }"
            " QFrame#dashCard QFrame { border: none; }"
            " QFrame#dashCard QProgressBar { border: none; }"
        )


def _label(text, size=13, bold=False, color=None, family=None):
    lbl = QLabel(text)
    weight = "bold" if bold else "normal"
    col = color or COLOR_ON_SURFACE
    fam = family or "Segoe UI,'Microsoft YaHei UI'"
    lbl.setStyleSheet(f"font-size:{size}px; font-weight:{weight}; color:{col}; font-family:{fam}; border:none; background:transparent;")
    return lbl


def _micro_label(text, color=COLOR_GRAY_TEXT):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"font-size:9px; font-weight:900; letter-spacing:0.5px; color:{color}; border:none; background:transparent;")
    return lbl


def _bar(pct: int, height=8, color="#4b89ff", bg="#eaecf4"):
    bar = QProgressBar()
    bar.setFixedHeight(height); bar.setValue(pct); bar.setTextVisible(False)
    bar.setStyleSheet(f"QProgressBar{{background:{bg};border-radius:{height//2}px;border:none;}}"
                      f"QProgressBar::chunk{{background:{color};border-radius:{height//2}px;border:none;}}")
    return bar


# ─────────────────────────────────────────────
#  小型数据盒（VRAM / TEMP）
# ─────────────────────────────────────────────
class StatBox(QFrame):
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statBox")
        self.setStyleSheet(
            "QFrame#statBox { background:#f5f7fb; border-radius:12px; border:none; }"
            " QFrame#statBox QLabel { border:none; background:transparent; }")
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 10, 14, 10); lay.setSpacing(4)
        lay.addWidget(_micro_label(label))
        self._val = QLabel(value)
        self._val.setStyleSheet(f"font-size:16px;font-weight:800;color:{COLOR_ON_SURFACE};border:none;")
        lay.addWidget(self._val)

    def set_value(self, v: str):
        self._val.setText(v)


# ─────────────────────────────────────────────
#  主 Widget
# ─────────────────────────────────────────────
class DashboardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

        # ── 启动后台监控线程（不阻塞主线程） ───
        self._worker = MonitorWorker(interval_ms=4000, parent=None)  # 不设 parent，手动管理生命周期
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.start()

        # 当 Widget 被销毁时自动停止线程（兜底）
        self.destroyed.connect(self.stop_monitoring)

        # 页面加载后稍延初始化静态信息，避免占用启动耗时
        QTimer.singleShot(100, self._init_hardware_static_info)

    def stop_monitoring(self):
        """公开方法：安全停止后台监控线程（主窗口关闭时应主动调用）"""
        if self._worker and self._worker.isRunning():
            self._worker.stop()

    # ── 初始化静态数据（运行一次） ──────────────────
    def _init_hardware_static_info(self):
        info = MonitoringEngine.get_static_info()
        # CPU
        self._lbl_cpu_model.setText(info["cpu_model"])
        # RAM
        self._lbl_ram_total.setText(f"总量 {info['total_ram_gb']} GB")
        # GPU
        self._lbl_gpu_model.setText(info["gpu_model"])
        # 存储 - 动态构建磁盘列表
        self._rebuild_disk_list(info["disks"])

    # ── 构建 UI ──────────────────────────────
    def _setup_ui(self):
        # 外层支持滚动
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 性能：开启静态内容标志，减少视口重绘频率
        scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StaticContents)
        # 减少视口自动背景刷新，优化滚动性能
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(40, 40, 40, 56)
        lay.setSpacing(32)

        # ── 1. 页面标题 ──
        header = QVBoxLayout(); header.setSpacing(6)
        lbl = _label("系统实时心跳", 10, True, "#4b89ff")
        lbl.setStyleSheet("font-size:10px;font-weight:900;letter-spacing:1.5px;color:#4b89ff;")
        header.addWidget(lbl)
        header.addWidget(_label("硬件监控概览", 36, True, COLOR_ON_SURFACE, "Manrope"))
        desc = _label(
            "通过专业审计视角，精准掌握系统状态。当前系统运行温度及各项参数\n"
            "均处于理想且稳定的范围内。", 14, False, COLOR_ON_SURFACE_VARIANT)
        desc.setWordWrap(True)
        header.addWidget(desc)
        lay.addLayout(header)

        # ── 2. 第一行：CPU + RAM ──
        row1 = QHBoxLayout(); row1.setSpacing(24)
        row1.addWidget(self._build_cpu_card(), 3)
        row1.addWidget(self._build_ram_card(), 2)
        lay.addLayout(row1)

        # ── 3. 第二行：GPU + 存储 ──
        row2 = QHBoxLayout(); row2.setSpacing(24)
        row2.addWidget(self._build_gpu_card(), 1)
        row2.addWidget(self._build_disk_card(), 1)
        lay.addLayout(row2)

        # ── 4. 第三行：散热 + 线程 ──
        row3 = QHBoxLayout(); row3.setSpacing(24)
        row3.addWidget(self._build_cooling_card(), 1)
        row3.addWidget(self._build_threads_card(), 1)
        lay.addLayout(row3)

        # ── 5. 悬浮 Boost 按钮 ──
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        self._btn_boost = QPushButton("  ⚡  性能加速")
        self._btn_boost.setFixedSize(188, 58)
        self._btn_boost.setStyleSheet(
            f"QPushButton{{background:{COLOR_PRIMARY};color:white;"
            f"border-radius:29px;font-weight:900;font-size:15px;}}"
            f"QPushButton:hover{{background:{COLOR_PRIMARY_VARIANT};}}")
        btn_lay.addWidget(self._btn_boost)
        lay.addLayout(btn_lay)

    # ── CPU 卡片 ──────────────────────────────
    def _build_cpu_card(self) -> Card:
        card = Card(); card.setMinimumHeight(230)
        h = QHBoxLayout(card); h.setContentsMargins(30, 30, 30, 30)

        left = QVBoxLayout(); left.setSpacing(10)

        title_row = QHBoxLayout()
        icon = QLabel("💻"); icon.setStyleSheet("font-size:24px;")
        title_row.addWidget(icon)
        title_row.addWidget(_label("中央处理器", 18, True))
        title_row.addStretch()
        left.addLayout(title_row)

        left.addSpacing(6)
        left.addWidget(_micro_label("处理器单元"))
        self._lbl_cpu_model = _label("正在获取...", 16, True)
        self._lbl_cpu_model.setWordWrap(True)
        left.addWidget(self._lbl_cpu_model)

        metrics = QHBoxLayout(); metrics.setSpacing(28)
        for attr, title in [("_lbl_cpu_clock", "核心时钟"), ("_lbl_cpu_temp", "核心温度")]:
            vb = QVBoxLayout(); vb.setSpacing(3)
            vb.addWidget(_micro_label(title))
            lbl = _label("–", 17, True)
            setattr(self, attr, lbl)
            vb.addWidget(lbl)
            metrics.addLayout(vb)
        metrics.addStretch()
        left.addLayout(metrics)

        h.addLayout(left, 1)
        self._cpu_gauge = CpuDonut()
        h.addWidget(self._cpu_gauge)
        return card

    # ── RAM 卡片 ──────────────────────────────
    def _build_ram_card(self) -> Card:
        card = Card(); card.setMinimumHeight(230)
        v = QVBoxLayout(card); v.setContentsMargins(28, 26, 28, 26)

        top = QHBoxLayout()
        icon = QLabel("📟"); icon.setStyleSheet("font-size:22px;")
        top.addWidget(icon)
        top.addWidget(_label("内存条", 17, True))
        top.addStretch()
        tag = QLabel("DDR5")
        tag.setStyleSheet("background:#eeeff5;border-radius:8px;padding:3px 10px;"
                          "font-size:11px;font-weight:900;color:#8888a0;")
        top.addWidget(tag)
        v.addLayout(top)

        self._ram_gauge = RamDonut()
        v.addWidget(self._ram_gauge, 0, Qt.AlignmentFlag.AlignCenter)

        bot = QHBoxLayout()
        bot.addWidget(_label("可用容量", 10, False, COLOR_GRAY_TEXT))
        bot.addStretch()
        self._lbl_ram_total = _label("– GB 总计", 10, True)
        bot.addWidget(self._lbl_ram_total)
        v.addLayout(bot)

        # 进度条
        self._ram_bar = _bar(0, 6, "#7c5cfc")
        v.addWidget(self._ram_bar)
        return card

    # ── GPU 卡片 ──────────────────────────────
    def _build_gpu_card(self) -> Card:
        card = Card(); card.setMinimumHeight(260)
        v = QVBoxLayout(card); v.setContentsMargins(30, 28, 30, 28); v.setSpacing(10)

        top = QHBoxLayout()

        icon_box = QFrame()
        icon_box.setStyleSheet("background:#eef1f8;border-radius:12px;")
        icon_box.setFixedSize(42, 42)
        ib = QHBoxLayout(icon_box); ib.setContentsMargins(8,8,8,8)
        ib.addWidget(QLabel("⚙️", styleSheet="font-size:18px;"))
        
        top.addWidget(icon_box)
        top.addSpacing(8)
        top.addWidget(_label("图形处理引擎", 18, True))
        top.addStretch()

        clock_col = QVBoxLayout(); clock_col.setSpacing(2)
        clock_col.addWidget(_micro_label("CORE LOAD")) # 显存频率读取较难，统一显示核心负载
        self._lbl_gpu_load_text = _label("– %", 15, True)
        clock_col.addWidget(self._lbl_gpu_load_text)
        top.addLayout(clock_col)
        v.addLayout(top)

        self._lbl_gpu_model = _label("正在探测中...", 16, True)
        self._lbl_gpu_model.setWordWrap(True)
        v.addWidget(self._lbl_gpu_model)
        v.addWidget(_label("硬件加速模块", 11, False, COLOR_GRAY_TEXT))

        v.addSpacing(8)
        util_row = QHBoxLayout()
        util_row.addWidget(_micro_label("核心利用率"))
        util_row.addStretch()
        self._lbl_gpu_util = _label("82%", 12, True)
        util_row.addWidget(self._lbl_gpu_util)
        v.addLayout(util_row)

        self._gpu_bar = _bar(0)
        v.addWidget(self._gpu_bar)

        stat_row = QHBoxLayout(); stat_row.setSpacing(12)
        self._box_vram = StatBox("显存占用", "N/A")
        self._box_gpu_temp = StatBox("核心温度", "– °C")
        stat_row.addWidget(self._box_vram)
        stat_row.addWidget(self._box_gpu_temp)
        v.addLayout(stat_row)
        return card

    # ── 存储卡片 ─────────────────────────────
    def _build_disk_card(self) -> Card:
        card = Card(); card.setMinimumHeight(260)
        v = QVBoxLayout(card); v.setContentsMargins(30, 28, 30, 28); v.setSpacing(14)

        top = QHBoxLayout()
        icon_box = QFrame(); icon_box.setStyleSheet("background:#eef1f8;border-radius:12px;")
        icon_box.setFixedSize(42, 42)
        ib2 = QHBoxLayout(icon_box); ib2.setContentsMargins(8,8,8,8)
        ib2.addWidget(QLabel("🗄️", styleSheet="font-size:18px;"))
        top.addWidget(icon_box); top.addSpacing(8)
        top.addWidget(_label("存储系统架构", 18, True)); top.addStretch()
        v.addLayout(top)

        # 磁盘列表容器
        self._disk_container = QVBoxLayout(); self._disk_container.setSpacing(14)
        v.addLayout(self._disk_container)
        v.addStretch()

        return card

    def _rebuild_disk_list(self, disks):
        # 清除旧的
        while self._disk_container.count():
            item = self._disk_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self._disk_bars = [] # 记录下来以便刷新

        for disk in disks[:3]: # 最多显示前三个活跃盘符
            row_l = QHBoxLayout()
            di = QFrame(); di.setStyleSheet("background:#eef1f8;border-radius:10px;")
            di.setFixedSize(34, 34)
            dil = QHBoxLayout(di); dil.setContentsMargins(5,5,5,5)
            dil.addWidget(QLabel("💾", styleSheet="font-size:14px;"))
            row_l.addWidget(di); row_l.addSpacing(8)

            info_lay = QVBoxLayout(); info_lay.setSpacing(4)
            title_r = QHBoxLayout()
            title_r.addWidget(_label(f"{disk['device']} ({disk['mount']})", 12, True))
            title_r.addStretch()
            
            free_gb = disk['free'] / (1024**3)
            total_gb = disk['total'] / (1024**3)
            lbl_cap = _label(f"可用 {free_gb:.1f} GB / 总计 {int(total_gb)} GB", 10, False, COLOR_GRAY_TEXT)
            title_r.addWidget(lbl_cap)
            info_lay.addLayout(title_r)
            
            pbar = _bar(int(disk['percent']), 8)
            info_lay.addWidget(pbar)
            row_l.addLayout(info_lay)
            
            # 使用列表存储引用以供刷新可用空间时使用
            # 虽然由于 get_static_info 已经包含了百分比，这里主要记录 widget
            self._disk_container.addLayout(row_l)

    # ── 散热卡片 ─────────────────────────────
    def _build_cooling_card(self) -> Card:
        card = Card()
        h = QHBoxLayout(card); h.setContentsMargins(30, 30, 30, 30)

        left = QVBoxLayout(); left.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(QLabel("❄️", styleSheet="font-size:20px;"))
        top.addWidget(_label("自适应散热系统", 17, True))
        top.addStretch()
        left.addLayout(top)

        left.addSpacing(12)
        left.addWidget(_micro_label("当前转速"))
        self._lbl_fan_rpm = _label("1420 RPM", 32, True)
        self._lbl_fan_rpm.setStyleSheet(f"font-size:32px;font-weight:900;color:#1c1c1e;font-family: {FONT_FAMILY_TITLE};")
        left.addWidget(self._lbl_fan_rpm)
        h.addLayout(left, 1)

        fan_icon = QLabel("🌀")
        fan_icon.setStyleSheet("font-size:42px;")
        h.addWidget(fan_icon)
        return card

    # ── 线程卡片 ─────────────────────────────
    def _build_threads_card(self) -> Card:
        card = Card()
        v = QVBoxLayout(card); v.setContentsMargins(30, 30, 30, 30); v.setSpacing(14)

        top = QHBoxLayout()
        top.addWidget(QLabel("📋", styleSheet="font-size:20px;"))
        top.addWidget(_label("活动线程监控", 17, True))
        top.addStretch()
        v.addLayout(top)

        # 进程色点
        dot_row = QHBoxLayout(); dot_row.setSpacing(8)
        for col in ["#4b89ff", "#7c5cfc", "#adb3c3"]:
            dot = QFrame()
            dot.setFixedSize(32, 32)
            dot.setStyleSheet(f"background:{col};border-radius:16px;")
            dot_row.addWidget(dot)
        dot_row.addSpacing(10)
        self._lbl_threads = _label("142 个后台子任务", 14, False, COLOR_ON_SURFACE_VARIANT)
        dot_row.addWidget(self._lbl_threads)
        dot_row.addStretch()
        v.addLayout(dot_row)
        return card

    # ── 数据处理（信号接收端，运行在主线程） ─────────────────
    def _on_data_ready(self, snapshot: dict):
        """
        接收后台线程推应的硬件快照数据并更新所有使用。
        这里不执行任何 IO / 子进程，就是纯粿的 Python 赋值语句。
        """
        try:
            # CPU
            self._cpu_gauge.set_value(snapshot["cpu_percent"])
            self._lbl_cpu_clock.setText(snapshot["cpu_clock"])
            self._lbl_cpu_temp.setText(snapshot["cpu_temp"])

            # RAM
            self._ram_gauge.set_value(snapshot["ram_used_gb"], snapshot["ram_total_gb"])
            self._ram_bar.setValue(int(snapshot["ram_percent"]))

            # GPU
            gpu_u = snapshot["gpu_util"]
            self._gpu_bar.setValue(gpu_u)
            self._lbl_gpu_load_text.setText(f"{gpu_u}%")
            self._lbl_gpu_util.setText(f"{gpu_u}%" if snapshot["gpu_util_ok"] else "N/A")

            # 散热
            self._lbl_fan_rpm.setText(snapshot["fan_rpm"])

            # 进程数
            self._lbl_threads.setText(f"{snapshot['process_count']} 个活动进程")
        except Exception:
            pass
