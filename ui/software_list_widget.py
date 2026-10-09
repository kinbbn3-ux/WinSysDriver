# -*- coding: utf-8 -*-
"""
软件包卡片列表组件

以卡片式布局展示软件包信息，包含：
- 左侧 4px 竖线色条（状态指示）
- 软件图标（QFileIconProvider，< 1ms 无性能损耗）
- 软件名、大小、类型标签、静默参数
- 状态徽章（等待/安装中/成功/失败）
- 安装中时的内嵌进度条
- 右键菜单：编辑参数、跳过、重试
"""

from __future__ import annotations
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QCheckBox, QPushButton, QProgressBar,
    QSizePolicy, QMenu, QInputDialog, QMessageBox, QFileIconProvider
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon

from models.package_info import PackageInfo, SoftwareInstallerType, PackageType
from models.driver_info import InstallStatus
from ui.styles import (
    COLOR_WHITE, COLOR_ON_SURFACE, COLOR_ON_SURFACE_VARIANT, COLOR_SURFACE,
    COLOR_GRAY_TEXT, COLOR_SURFACE_CONTAINER,
    COLOR_STATUS_PENDING, COLOR_STATUS_ACTIVE,
    COLOR_STATUS_SUCCESS, COLOR_STATUS_FAILURE, COLOR_STATUS_SKIPPED,
    COLOR_BADGE_BG, COLOR_BADGE_TEXT, COLOR_PILL_BG,
)

# 状态 → 竖线颜色
_STATUS_COLOR_MAP = {
    InstallStatus.PENDING:       COLOR_STATUS_PENDING,
    InstallStatus.INSTALLING:    COLOR_STATUS_ACTIVE,
    InstallStatus.SUCCESS:       COLOR_STATUS_SUCCESS,
    InstallStatus.FAILED:        COLOR_STATUS_FAILURE,
    InstallStatus.SKIPPED:       COLOR_STATUS_SKIPPED,
    InstallStatus.REBOOT_NEEDED: COLOR_STATUS_SUCCESS,
}

# 状态 → 显示文本
_STATUS_TEXT_MAP = {
    InstallStatus.PENDING:       "⏳ 等待",
    InstallStatus.INSTALLING:    "🔄 安装中",
    InstallStatus.SUCCESS:       "✅ 成功",
    InstallStatus.FAILED:        "❌ 失败",
    InstallStatus.SKIPPED:       "⏭ 跳过",
    InstallStatus.REBOOT_NEEDED: "🔁 需重启",
}

# 安装类型 → 徽章颜色（轻量色系）
_TYPE_BADGE_BG = {
    "Inno Setup":    "#e0f0ff",
    "NSIS":          "#eef7e0",
    "InstallShield": "#fff5e0",
    "MSI":           "#ede0ff",
    "Office ODT":    "#ffd6c9",
    "ZIP":           "#f0f0f0",
    "磁盘镜像":      "#e0f7fa",
    "便携软件":      "#f3e5f5",
    "未知":          "#f0f0f0",
}
_TYPE_BADGE_COLOR = {
    "Inno Setup":    "#0059cc",
    "NSIS":          "#1a7a1a",
    "InstallShield": "#935a00",
    "MSI":           "#6a1aad",
    "Office ODT":    "#c83000",
    "ZIP":           "#5a5a5a",
    "磁盘镜像":      "#00838f",
    "便携软件":      "#7b1fa2",
    "未知":          "#5a5a5a",
}

_ICON_PROVIDER = QFileIconProvider()


def _get_file_icon(file_path: str) -> QIcon:
    """使用 QFileIconProvider 快速获取文件图标（< 1ms）"""
    from PySide6.QtCore import QFileInfo
    try:
        return _ICON_PROVIDER.icon(QFileInfo(file_path))
    except Exception:
        return QIcon()


# ─────────────────────────────────────────────
#  单个软件包卡片
# ─────────────────────────────────────────────
class PackageCard(QFrame):
    """
    单个软件包卡片组件

    信号：
      edit_args_requested(PackageInfo)  → 请求编辑静默参数
      retry_requested(PackageInfo)      → 请求重试安装
    """
    edit_args_requested = Signal(object)
    retry_requested     = Signal(object)

    def __init__(self, pkg: PackageInfo, parent=None):
        super().__init__(parent)
        self._pkg = pkg
        self.setObjectName("pkgCard")
        self.setStyleSheet("QFrame#pkgCard { background: " + COLOR_WHITE + "; border-radius: 16px; border: 1px solid #eaedf3; }"
                          " QFrame#pkgCard QLabel { border: none; background: transparent; }")
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 16, 0)
        root.setSpacing(0)

        # ① 左侧竖线色条（状态指示）
        self._bar = QFrame()
        self._bar.setFixedWidth(5)
        self._bar.setStyleSheet(f"background: {COLOR_STATUS_PENDING}; border-radius: 5px;")
        root.addWidget(self._bar)
        root.addSpacing(12)

        # ② 勾选框
        self._check = QCheckBox()
        self._check.setChecked(self._pkg.enabled)
        self._check.setFixedWidth(24)
        self._check.stateChanged.connect(self._on_check_changed)
        root.addWidget(self._check)
        root.addSpacing(10)

        # ③ 软件图标 (16×16 从 Windows Shell 提取)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(32, 32)
        icon = _get_file_icon(self._pkg.file_path)
        if not icon.isNull():
            icon_lbl.setPixmap(icon.pixmap(28, 28))
        else:
            icon_lbl.setText("📦")
            icon_lbl.setStyleSheet("font-size: 20px;")
        root.addWidget(icon_lbl)
        root.addSpacing(12)

        # ④ 主信息区（名称 + 元信息行）
        info_col = QVBoxLayout()
        info_col.setSpacing(4)
        info_col.setContentsMargins(0, 14, 0, 14)

        # 软件名
        self._lbl_name = QLabel(self._pkg.name)
        self._lbl_name.setStyleSheet(f"font-weight: 800; font-size: 14px; color: {COLOR_ON_SURFACE};")
        info_col.addWidget(self._lbl_name)

        # 元信息行：大小 + 类型徽章 + 静默参数
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)

        # 文件大小
        lbl_size = QLabel(self._pkg.get_display_size())
        lbl_size.setStyleSheet(f"font-size: 11px; color: {COLOR_GRAY_TEXT};")
        meta_row.addWidget(lbl_size)

        # 类型徽章
        type_badge = self._make_type_badge(self._pkg.get_type_badge())
        meta_row.addWidget(type_badge)

        # 签名徽章（仅 EXE / MSI，跳过 ZIP）
        from models.package_info import SigStatus
        sig_texts = {
            SigStatus.VALID:      ("🔐 签名有效", "#00a65a", "#eafaf0"),
            SigStatus.NOT_SIGNED: ("⚠️ 无签名", "#f39c12", "#fff8e8"),
            SigStatus.TAMPERED:   ("❌ 签名异常", "#dd4b39", "#fff0ef"),
            SigStatus.ERROR:      ("❓ 核验出错", COLOR_GRAY_TEXT, "#f0f0f0"),
            SigStatus.UNCHECKED:  ("", "", ""),
        }
        sig_text, sig_fg, sig_bg = sig_texts.get(self._pkg.sig_status, ("", "", ""))
        if sig_text and self._pkg.package_type != PackageType.ZIP:
            lbl_sig = QLabel(sig_text)
            lbl_sig.setStyleSheet(f"font-size: 10px; font-weight: bold; color: {sig_fg}; background: {sig_bg}; border-radius: 4px; padding: 2px 6px;")
            if self._pkg.sig_signer:
                lbl_sig.setToolTip(f"签名者：{self._pkg.sig_signer}")
            meta_row.addWidget(lbl_sig)

        # ZIP 专有配置（创建桌面快捷方式）
        if self._pkg.package_type == PackageType.ZIP:
            self._chk_shortcut = QCheckBox("创建快捷方式")
            self._chk_shortcut.setChecked(self._pkg.create_shortcut)
            self._chk_shortcut.setStyleSheet(f"font-size: 11px; color: {COLOR_ON_SURFACE_VARIANT};")
            self._chk_shortcut.stateChanged.connect(self._on_shortcut_changed)
            meta_row.addWidget(self._chk_shortcut)

        # 静默参数（若不为空显示）
        args = self._pkg.get_effective_args()
        if args and self._pkg.package_type != PackageType.ZIP:
            lbl_args = QLabel(" ".join(args))
            lbl_args.setStyleSheet(f"font-size: 11px; color: {COLOR_ON_SURFACE_VARIANT}; "
                                   f"background: {COLOR_SURFACE_CONTAINER}; border-radius: 4px; padding: 2px 6px;")
            lbl_args.setFont(__import__("PySide6.QtGui", fromlist=["QFont"]).QFont("Consolas", 10))
            meta_row.addWidget(lbl_args)

        meta_row.addStretch()
        info_col.addLayout(meta_row)

        # 错误信息行（失败时显示）
        self._lbl_error = QLabel()
        self._lbl_error.setStyleSheet(f"font-size: 11px; color: {COLOR_STATUS_FAILURE};")
        self._lbl_error.setWordWrap(True)
        self._lbl_error.setVisible(False)
        info_col.addWidget(self._lbl_error)

        # 内嵌进度条（安装中时显示）
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(5)
        self._progress_bar.setRange(0, 0)  # 不确定进度（动态滚动）
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {COLOR_SURFACE_CONTAINER}; border-radius: 3px; border: none; }}"
            f"QProgressBar::chunk {{ background: {COLOR_STATUS_ACTIVE}; border-radius: 3px; }}"
        )
        self._progress_bar.setVisible(False)
        info_col.addWidget(self._progress_bar)

        root.addLayout(info_col, 1)

        # ⑤ 状态徽章（右侧）
        self._lbl_status = QLabel("⏳ 等待")
        self._lbl_status.setStyleSheet(
            f"font-size: 11px; font-weight: 800; color: {COLOR_STATUS_PENDING}; "
            f"background: #fff8e8; border-radius: 10px; padding: 3px 10px;")
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._lbl_status)

    def _make_type_badge(self, type_text: str) -> QLabel:
        bg = _TYPE_BADGE_BG.get(type_text, "#f0f0f0")
        fg = _TYPE_BADGE_COLOR.get(type_text, "#5a5a5a")
        lbl = QLabel(type_text)
        lbl.setStyleSheet(f"font-size: 10px; font-weight: 900; color: {fg}; "
                          f"background: {bg}; border-radius: 8px; padding: 2px 8px;")
        return lbl

    def _on_check_changed(self, state):
        self._pkg.enabled = (state == Qt.CheckState.Checked.value)

    def _on_shortcut_changed(self, state):
        self._pkg.create_shortcut = (state == Qt.CheckState.Checked.value)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(f"QMenu {{ background: {COLOR_WHITE}; border: 1px solid #e0e4ec; border-radius: 8px; }}"
                           f"QMenu::item:selected {{ background: #f0f7ff; color: #0059cc; }}")
        act_edit = menu.addAction("✏️ 编辑静默参数")
        act_retry = menu.addAction("🔄 重试安装")
        act_skip = menu.addAction("⏭ 跳过此包")
        act = menu.exec(self.mapToGlobal(pos))
        if act == act_edit:
            self.edit_args_requested.emit(self._pkg)
        elif act == act_retry:
            self.retry_requested.emit(self._pkg)
        elif act == act_skip:
            self._pkg.enabled = False
            self._check.setChecked(False)

    # ── 公开更新接口 ──────────────────────────────────────────────────────
    def update_status(self, status: InstallStatus, error_msg: str = ""):
        """更新卡片状态（供外部调用）"""
        color = _STATUS_COLOR_MAP.get(status, COLOR_GRAY_TEXT)
        text  = _STATUS_TEXT_MAP.get(status, "–")

        # 竖线色条
        self._bar.setStyleSheet(f"background: {color}; border-radius: 5px;")

        # 状态徽章文字 + 颜色
        badge_bg = {
            InstallStatus.PENDING:    "#fff8e8",
            InstallStatus.INSTALLING: "#eef4ff",
            InstallStatus.SUCCESS:    "#eafaf0",
            InstallStatus.FAILED:     "#fff0ef",
            InstallStatus.SKIPPED:    "#f2f2f2",
        }.get(status, "#f2f2f2")
        self._lbl_status.setText(text)
        self._lbl_status.setStyleSheet(
            f"font-size: 11px; font-weight: 800; color: {color}; "
            f"background: {badge_bg}; border-radius: 10px; padding: 3px 10px;")

        # 进度条（仅安装中时展示）
        self._progress_bar.setVisible(status == InstallStatus.INSTALLING)

        # 错误信息
        if status == InstallStatus.FAILED and error_msg:
            self._lbl_error.setText(f"⚠ {error_msg}")
            self._lbl_error.setVisible(True)
        else:
            self._lbl_error.setVisible(False)

    def set_interactive(self, enabled: bool):
        self._check.setEnabled(enabled)

    @property
    def package(self) -> PackageInfo:
        return self._pkg


# ─────────────────────────────────────────────
#  软件包列表容器
# ─────────────────────────────────────────────
class SoftwareListWidget(QWidget):
    """
    软件包卡片列表组件

    管理所有 PackageCard 的创建、更新与交互。

    信号：
      package_edit_requested(PackageInfo) → 某个包请求编辑参数
    """
    package_edit_requested = Signal(object)
    package_retry_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, PackageCard] = {}  # file_path → card
        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 空状态提示
        self._empty_label = QLabel("📂 请先选择包含安装包的文件夹")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 15px; padding: 60px;")
        outer.addWidget(self._empty_label)

        # 卡片滚动区域
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setVisible(False)
        outer.addWidget(self._scroll)

        self._container = QWidget()
        self._container.setStyleSheet(f"background: {COLOR_SURFACE};")
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._container)

    # ── 数据接口 ──────────────────────────────────────────────────────────
    def set_packages(self, packages: list[PackageInfo]):
        """用新的包列表刷新卡片区域"""
        # 清除旧卡片
        self._cards.clear()
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not packages:
            self._empty_label.setVisible(True)
            self._scroll.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self._scroll.setVisible(True)

        for pkg in packages:
            card = PackageCard(pkg)
            card.edit_args_requested.connect(self.package_edit_requested)
            card.retry_requested.connect(self.package_retry_requested)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)
            self._cards[pkg.file_path] = card

    def update_package_status(self, pkg: PackageInfo, error_msg: str = ""):
        """更新指定包的卡片状态"""
        card = self._cards.get(pkg.file_path)
        if card:
            card.update_status(pkg.status, error_msg)

    def get_packages(self) -> list[PackageInfo]:
        """获取所有包信息（含用户勾选状态）"""
        return [c.package for c in self._cards.values()]

    def get_enabled_count(self) -> int:
        """获取已勾选（启用）的包数量"""
        return sum(1 for c in self._cards.values() if c.package.enabled)

    def set_interactive(self, enabled: bool):
        """锁定/解锁所有卡片的交互状态"""
        for card in self._cards.values():
            card.set_interactive(enabled)

    # ── 统计摘要 ──────────────────────────────────────────────────────────
    def get_summary(self) -> dict[str, int]:
        """返回各类型的数量统计"""
        summary = {"EXE": 0, "MSI": 0, "ZIP": 0, "Office": 0, "Total": 0}
        for c in self._cards.values():
            pkg = c.package
            if pkg.installer_type == SoftwareInstallerType.OFFICE_ODT:
                summary["Office"] += 1
            elif pkg.installer_type == SoftwareInstallerType.PORTABLE_APP:
                summary["便携软件"] = summary.get("便携软件", 0) + 1
            elif pkg.package_type == PackageType.MSI:
                summary["MSI"] += 1
            elif pkg.package_type == PackageType.ZIP:
                summary["ZIP"] += 1
            elif pkg.package_type == PackageType.ISO:
                summary["ISO"] = summary.get("ISO", 0) + 1
            else:
                summary["EXE"] += 1
            summary["Total"] += 1
        return summary
