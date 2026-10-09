# -*- coding: utf-8 -*-
"""
Ethereal Technician - UI 设计系统主题与样式定义

提供现代化的色彩、字体、阴影以及圆角规范。
"""

import os

# --- 色彩规范 (Stitch-inspired) ---
COLOR_PRIMARY = "#0059cc"           # 主色：深蓝
COLOR_PRIMARY_VARIANT = "#004db4"   # 主色变体
COLOR_SURFACE = "#f6faff"           # 全局背景（无边框呼吸感）
COLOR_SURFACE_CONTAINER = "#e7eff6" # 容器底色
COLOR_ON_SURFACE = "#1c1c1e"        # 文字主色
COLOR_ON_SURFACE_VARIANT = "#8e8e93" # 文字次色
COLOR_WHITE = "#ffffff"             # 纯白（大圆角卡片专用）

# --- 补充色彩 (设计图特定) ---
COLOR_BADGE_BG = "#eaf2fd"          # 徽章背景 (淡蓝)
COLOR_BADGE_TEXT = "#0059cc"        # 徽章文字 (主色)
COLOR_PILL_BG = "#eff3f8"           # 药丸/标签背景 (淡灰)
COLOR_GRAY_TEXT = "#8a8a8e"         # 辅助文本灰

# --- 软件安装状态色 ---
COLOR_STATUS_PENDING = "#D29922"    # 琥珀：等待安装
COLOR_STATUS_ACTIVE  = "#4b89ff"    # 蓝色：安装中
COLOR_STATUS_SUCCESS = "#2EA043"    # 翠绿：安装成功
COLOR_STATUS_FAILURE = "#F85149"    # 朱红：安装失败
COLOR_STATUS_SKIPPED = "#8a8a8e"    # 灰色：已跳过

# --- 视觉参数 ---
RADIUS_LG = "32px"                  # 大圆角
RADIUS_MD = "16px"                  # 中圆角
RADIUS_SM = "8px"                   # 小圆角

# --- 字体规范 ---
# 标题：Manrope (西文) + Windows 中文字体
# 正文：Windows 中文字体 + Segoe UI
# 技术数据：JetBrains Mono (等宽)
FONT_FAMILY_TITLE = "'Manrope', 'Microsoft YaHei UI', 'Segoe UI', sans-serif"
FONT_FAMILY_BODY  = "'Microsoft YaHei UI', 'Segoe UI', sans-serif"
FONT_FAMILY_MONO  = "'JetBrains Mono', 'Consolas', monospace"

# --- QSS 样式表模板 ---
QSS_MAIN_STYLE = f"""
QMainWindow {{
    background-color: {COLOR_SURFACE};
}}

QWidget {{
    border: none;
    font-family: {FONT_FAMILY_BODY};
    font-size: 14px;
    color: {COLOR_ON_SURFACE};
}}

/* 标准普通按钮 */
QPushButton {{
    background-color: {COLOR_WHITE};
    border: 1px solid #d1d9e6;
    border-radius: {RADIUS_SM};
    padding: 6px 16px;
    color: {COLOR_ON_SURFACE};
    font-family: {FONT_FAMILY_BODY};
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {COLOR_SURFACE_CONTAINER};
    border: 1px solid #c2ccdf;
}}

QPushButton:pressed {{
    background-color: #dbe7f2;
}}

/* 胶囊导航按钮 */
QPushButton#nav_button {{
    background-color: transparent;
    color: {COLOR_ON_SURFACE_VARIANT};
    border-radius: {RADIUS_MD};
    padding: 8px 16px;
    font-weight: 500;
    text-align: left;
    font-family: {FONT_FAMILY_TITLE};
}}

QPushButton#nav_button:hover {{
    background-color: {COLOR_SURFACE_CONTAINER};
    color: {COLOR_ON_SURFACE};
}}

QPushButton#nav_button:checked {{
    background-color: {COLOR_PRIMARY};
    color: {COLOR_WHITE};
}}

/* 行动操作按钮 (CTA) */
QPushButton#primary_button {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {COLOR_PRIMARY}, stop:1 {COLOR_PRIMARY_VARIANT});
    color: {COLOR_WHITE};
    border-radius: 24px;
    padding: 10px 24px;
    font-weight: bold;
    font-family: {FONT_FAMILY_TITLE};
}}

QPushButton#primary_button:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a6fd3, stop:1 #0059cc);
}}

/* 卡片布局 */
QFrame#card {{
    background-color: {COLOR_WHITE};
    border-radius: {RADIUS_LG};
}}

/* 无边框 Tab 平替 (QStackedWidget) */
QStackedWidget {{
    background-color: transparent;
}}

/* 进度条定制 */
QProgressBar {{
    background-color: {COLOR_SURFACE_CONTAINER};
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {COLOR_PRIMARY};
    border-radius: 6px;
}}

/* 树形列表 (驱动列表) */
QTreeWidget {{
    background-color: transparent;
    alternate-background-color: {COLOR_SURFACE_CONTAINER};
    border: none;
    outline: none;
    margin-top: 10px;
}}

QTreeWidget::item {{
    height: 64px;
    border-bottom: 8px solid {COLOR_SURFACE}; /* 模拟卡片间距 */
    background-color: {COLOR_WHITE};
    border-radius: {RADIUS_SM};
    padding: 0px 5px;
}}

QTreeWidget::item:selected {{
    background-color: #f0f7ff;
    color: {COLOR_PRIMARY};
    border: none;
}}

QHeaderView::section {{
    background-color: transparent;
    padding: 10px;
    border: none;
    font-weight: bold;
    color: {COLOR_ON_SURFACE_VARIANT};
    font-family: {FONT_FAMILY_TITLE};
}}

/* 下拉框与输入美化 */
QComboBox {{
    background-color: {COLOR_SURFACE_CONTAINER};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 2px 10px;
}}

QComboBox:hover {{
    background-color: #dbe7f2;
}}

/* 修复下拉框展开列表背景透明导致字体叠化（重影）的问题 */
QComboBox QAbstractItemView {{
    background-color: {COLOR_WHITE};
    selection-background-color: #f0f7ff;
    selection-color: {COLOR_PRIMARY};
    border: 1px solid #d1d9e6;
    border-radius: {RADIUS_SM};
    outline: none;
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    border: 1px solid #d1d9e6;
    border-radius: {RADIUS_SM};
    padding: 5px 8px;
    background-color: {COLOR_WHITE};
}}

/* 滚动条 */
QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 8px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background: #d1d9e6;
    min-height: 30px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: #bfc9d8;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* 英雄统计卡片 */
QFrame#hero_card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {COLOR_PRIMARY}, stop:1 {COLOR_PRIMARY_VARIANT});
    border-radius: 24px;
    padding: 20px;
}}

QLabel#hero_title {{
    color: rgba(255, 255, 255, 0.8);
    font-size: 14px;
    font-weight: 500;
}}

QLabel#hero_value {{
    color: {COLOR_WHITE};
    font-size: 42px;
    font-weight: 800;
    font-family: {FONT_FAMILY_TITLE};
}}

QLabel#stat_label {{
    background-color: {COLOR_WHITE};
    border-radius: 12px;
    padding: 10px 15px;
    font-weight: 600;
}}
"""

def get_res_path(rel_path: str) -> str:
    """获取资源绝对路径，确保 exe 打包后路径正确"""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'res', rel_path))
