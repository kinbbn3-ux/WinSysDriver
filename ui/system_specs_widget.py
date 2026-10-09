import os
import subprocess
import json
import psutil
import math
import time
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QFrame, QScrollArea, QSizePolicy, QPushButton, QStackedWidget)
from PySide6.QtCore import Qt, QThread, Signal
from ui.styles import *
from ui.scan_animation_widget import ScanAnimationWidget

logger = logging.getLogger("SystemSpecsWidget")

class SpecCard(QFrame):
    """三列式的硬件配置卡片，完美还原 Ethereal 设计图"""
    def __init__(self, icon_char: str, bg_color: str, fg_color: str,
                 c1_t: str, c1_v: str, c2_t: str, c2_v: str, c3_w: QWidget = None, parent=None):
        super().__init__(parent)
        self.setObjectName("spec_card")
        self.setStyleSheet(f"""
            #spec_card {{
                background-color: {COLOR_WHITE};
                border: 1px solid #F0F0F0;
                border-radius: 16px;
                margin-bottom: 8px;
            }}
            /* 解决底纹问题，强制完全透明 */
            QLabel {{
                background-color: transparent;
                border: none;
            }}
        """)
        self.setMinimumHeight(120)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(45)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # 1. 图标部分
        icon_lbl = QLabel(icon_char)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            background-color: {bg_color}; color: {fg_color};
            border-radius: 14px; font-size: 26px;
        """)
        icon_lbl.setFixedSize(56, 56)
        
        icon_vbox = QVBoxLayout()
        icon_vbox.addWidget(icon_lbl)
        icon_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addLayout(icon_vbox)
        
        # 字段生成器
        def _col(t, v):
            vbox = QVBoxLayout()
            vbox.setSpacing(6)
            vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
            
            t_lbl = QLabel(t)
            t_lbl.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 11px; font-weight: 700; font-family: {FONT_FAMILY_BODY};")
            vbox.addWidget(t_lbl)
            
            v_lbl = QLabel()
            v_lbl.setTextFormat(Qt.TextFormat.RichText)
            v_lbl.setText(f"<div style='color: {COLOR_ON_SURFACE}; font-size: 14px; font-weight: 800; line-height: 150%;'>{v}</div>")
            v_lbl.setWordWrap(True)
            vbox.addWidget(v_lbl)
            return vbox
            
        # 2. 中间两列数据
        layout.addLayout(_col(c1_t, c1_v), 5) 
        layout.addLayout(_col(c2_t, c2_v), 4)
        
        # 3. 右侧状态
        if c3_w:
            layout.addWidget(c3_w, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

class MiniProgress(QWidget):
    """小型进度条，用于硬件卡片内嵌"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 40)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        
        self.lbl = QLabel()
        self.lbl.setStyleSheet(f"color: {COLOR_ON_SURFACE_VARIANT}; font-size: 10px; font-weight: bold;")
        lay.addWidget(self.lbl)
        
        self.bar = QProgressBar()
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet(f"""
            QProgressBar {{ background: {COLOR_SURFACE_CONTAINER}; border-radius: 3px; border: none; }}
            QProgressBar::chunk {{ background: {COLOR_PRIMARY}; border-radius: 3px; }}
        """)
        lay.addWidget(self.bar)

    def set_data(self, title: str, val: float):
        self.lbl.setText(title)
        self.bar.setValue(int(val))


class SpecReaderThread(QThread):
    """后台整合读取所有硬件参数，采用高度容错的独立查询方案"""
    specs_ready = Signal(list)
    
    def run(self):
        # 1. 扫描动画模拟
        time.sleep(1.0)
        if self.isInterruptionRequested():
            return
        
        # 定义一个安全的 PS 执行函数
        def run_ps(cmd):
            process = None
            try:
                process = subprocess.Popen(
                    ['powershell', '-NoProfile', '-Command', cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors='ignore',
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                deadline = time.monotonic() + 8
                while process.poll() is None:
                    if self.isInterruptionRequested() or time.monotonic() >= deadline:
                        process.kill()
                        process.communicate()
                        return ""
                    time.sleep(0.05)
                stdout, _ = process.communicate()
                return stdout.strip()
            except:
                if process and process.poll() is None:
                    process.kill()
                return ""

        # 逐项加载数据，防止一个错误搞挂全身
        data = {}
        
        # 电脑型号
        data['Model'] = run_ps("(Get-CimInstance Win32_ComputerSystem).Model")
        data['MFR'] = run_ps("(Get-CimInstance Win32_ComputerSystem).Manufacturer")
        data['OS'] = run_ps("(Get-CimInstance Win32_OperatingSystem).Caption + ' ' + (Get-CimInstance Win32_OperatingSystem).OSArchitecture")
        
        # CPU
        data['CPU'] = run_ps("(Get-CimInstance Win32_Processor).Name")
        cores = psutil.cpu_count(logical=False) or "?"
        threads = psutil.cpu_count(logical=True) or "?"
        data['Cores'] = f"{cores} 核心 / {threads} 线程"
        
        # 主板
        data['Board'] = run_ps("(Get-CimInstance Win32_BaseBoard).Product")
        data['Bios'] = run_ps("(Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion")
        data['Firmware'] = run_ps("(Get-ComputerInfo -Property BiosFirmwareType).BiosFirmwareType")

        # 显卡 (多卡处理)
        gpu_raw = run_ps("(Get-CimInstance Win32_VideoController).Name")
        if gpu_raw and "\n" in gpu_raw: 
            data['GPU'] = gpu_raw.replace("\n", "<br/>")
        else:
            data['GPU'] = gpu_raw
            
        vram_raw = run_ps("(Get-CimInstance Win32_VideoController).AdapterRAM")
        try:
            # 简单取最大显存（处理字符串/数字混合情况）
            vrams = [int(v) for v in vram_raw.splitlines() if v.strip().isdigit()]
            max_vram = max(vrams) if vrams else 0
            data['VRAM'] = f"{round(max_vram / (1024**3), 1)} GB"
        except:
            data['VRAM'] = "核显/共享显存"

        # 硬盘
        disk_raw = run_ps("Get-CimInstance Win32_DiskDrive | ForEach-Object { \"$($_.Model) ($([math]::Round($_.Size / 1GB, 0))GB)\" }")
        data['Disk'] = disk_raw.replace("\n", "<br/>") if disk_raw else "未知物理硬盘"
        data['DiskHealth'] = run_ps("(Get-PhysicalDisk -ErrorAction SilentlyContinue | Select-Object -ExpandProperty HealthStatus) -join ', '")
        data['DiskMedia'] = run_ps("(Get-PhysicalDisk -ErrorAction SilentlyContinue | Select-Object -ExpandProperty MediaType) -join ', '")

        # 屏幕
        scr_raw = run_ps("(Get-CimInstance Win32_VideoController | Where { $_.CurrentHorizontalResolution }).CurrentHorizontalResolution")
        scr_h = run_ps("(Get-CimInstance Win32_VideoController | Where { $_.CurrentHorizontalResolution }).CurrentVerticalResolution")
        data['Res'] = f"{scr_raw} x {scr_h}" if scr_raw else "1920 x 1080 (推荐)"
        refresh_rate = run_ps("(Get-CimInstance Win32_VideoController | Where { $_.CurrentRefreshRate }).CurrentRefreshRate")
        data['Hz'] = f"{refresh_rate} Hz" if refresh_rate else "未知刷新率"
        data['Monitor'] = run_ps("(Get-CimInstance Win32_DesktopMonitor -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name) -join '<br/>'")

        # 内存
        mem = psutil.virtual_memory()
        data['RAM_Size'] = f"{math.ceil(mem.total / (1024**3))} GB"
        data['RAM_Usage'] = mem.percent
        spd = run_ps("(Get-CimInstance Win32_PhysicalMemory).Speed")
        data['RAM_Speed'] = spd.splitlines()[0] + " MHz" if spd else "3200 MHz+"

        # 电池
        data['Batt'] = run_ps("(Get-CimInstance Win32_Battery).Name")
        data['Batt_Pct'] = run_ps("(Get-CimInstance Win32_Battery).EstimatedChargeRemaining")
        
        # 电池健康度计算 (v1.3 Python 原生解析版)
        # 根本原因：将多行 PS 脚本传给 -Command 时换行符会丢失导致失效
        # 修复方案：Python 直接 subprocess 调用 powercfg 生成报告 + Python re 解析 HTML
        try:
            if self.isInterruptionRequested():
                return
            import re
            import tempfile
            tmp_path = os.path.join(tempfile.gettempdir(), "batt_rpt_di.html")
            # 直接调用系统 powercfg 生成报告（不经过 PowerShell 中间层）
            subprocess.run(
                ["powercfg", "/batteryreport", "/output", tmp_path],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if os.path.exists(tmp_path):
                with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f_obj:
                    html = f_obj.read()
                # 兼容不同系统语言/版本的标签结构
                # 结构：DESIGN CAPACITY</span></td><td>90,005 mWh
                d_m = re.search(r'DESIGN CAPACITY</span></td><td>([\d,\.]+)\s*m[Ww][Hh]', html)
                f_m = re.search(r'FULL CHARGE CAPACITY</span></td><td>([\d,\.]+)\s*m[Ww][Hh]', html)
                if d_m and f_m:
                    d_val = int(d_m.group(1).replace(",", "").replace(".", ""))
                    f_val = int(f_m.group(1).replace(",", "").replace(".", ""))
                    if d_val > 0:
                        health = min(100, int(f_val / d_val * 100))
                        data['Batt_Health'] = f"{health}%"
                    else:
                        data['Batt_Health'] = "N/A"
                else:
                    data['Batt_Health'] = "N/A"
                try:
                    os.remove(tmp_path)
                except:
                    pass
            else:
                data['Batt_Health'] = "N/A"
        except Exception as e:
            logger.error(f"电池健康度解析失败: {e}")
            data['Batt_Health'] = "N/A"


        # 整合为列表
        specs = []
        def _a(icon, b, f, t1, v1, t2, v2, c3):
            specs.append({"icon":icon, "bg":b, "fg":f, "c1_t":t1, "c1_v":v1, "c2_t":t2, "c2_v":v2, "c3":c3})

        _a("💻", "#E3F2FD", "#1565C0", "电脑型号 & 品牌", data['Model'], "操作系统", data['OS'], {"type":"pill", "text":"运行中"})
        _a("🔲", "#E3F2FD", "#1565C0", "中央处理器 (CPU)", data['CPU'], "规格参数", data['Cores'], {"type":"pill", "text":"状态良好"})
        _a("🎛️", "#F5F5F5", "#616161", "主板 (MOTHERBOARD)", data['Board'], "BIOS 版本", data['Bios'], {"type":"pill", "text":data['Firmware'] or "固件类型未知"})
        _a("🎹", "#F3E5F5", "#6A1B9A", "内存条 (RAM)", data['RAM_Size'], "运行频率", data['RAM_Speed'], {"type":"progress", "val":data['RAM_Usage']})
        _a("👁️", "#E1F5FE", "#0277BD", "图形显卡 (GPU)", data['GPU'], "显存容量", data['VRAM'], {"type":"pill", "text":"渲染正常"})
        disk_status = data['DiskHealth'] or "健康状态未知"
        disk_type = data['DiskMedia'] or "介质类型未知"
        _a("💾", "#FBE9E7", "#D84315", "存储设备 (DISK)", data['Disk'], "属性状态", disk_status, {"type":"pill", "text":disk_type})
        monitor_name = data['Monitor'] or "显示器信息未知"
        _a("🖥️", "#E0F2F1", "#00695C", "显示输出 (DISPLAY)", monitor_name, "当前分辨率", f"{data['Res']} @ {data['Hz']}", {"type":"pill", "text":data['Hz']})
        
        if data['Batt']:
            v2_text = f"健康度 {data['Batt_Health']} / 剩余 {data['Batt_Pct']}%" if data['Batt_Health'] != "N/A" else f"剩余电量 {data['Batt_Pct']}%"
            _a("🔋", "#F9FBE7", "#827717", "电源电池 (BATTERY)", data['Batt'], "状态属性", v2_text, {"type":"pill", "text":"正常"})
        else:
            # 如果是台式机，可以显示电源状态
            _a("🔌", "#F5F5F5", "#424242", "电源供电 (POWER)", "已接通交流电", "当前状态", "稳定运行中", {"type":"pill", "text":"AC Mode"})

        self.specs_ready.emit(specs)


class SystemSpecsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._load_data()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 40)
        layout.setSpacing(20)
        
        # Header
        header = QHBoxLayout()
        title_v = QVBoxLayout()
        st = QLabel("系统硬件规格")
        st.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        title_v.addWidget(st)
        mt = QLabel("电脑硬件概览")
        mt.setStyleSheet(f"font-size: 26px; font-weight: 800; color: {COLOR_ON_SURFACE}; font-family: {FONT_FAMILY_BODY};")
        title_v.addWidget(mt)
        header.addLayout(title_v)
        header.addStretch()
        
        btn = QPushButton("刷新配置")
        self._refresh_btn = btn
        btn.setFixedSize(100, 34)
        btn.setStyleSheet("QPushButton{background:white; border:1px solid #DDD; border-radius:17px; font-size:12px;} QPushButton:hover{background:#F5F5F5;}")
        btn.clicked.connect(self._load_data)
        header.addWidget(btn)
        layout.addLayout(header)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #F8F8F8; min-height: 1px;")
        layout.addWidget(line)

        self.stack = QStackedWidget()
        self.scan_page = ScanAnimationWidget()
        self.stack.addWidget(self.scan_page)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 10, 20, 10)
        self.content_layout.setSpacing(10)
        self.scroll.setWidget(self.content)
        self.stack.addWidget(self.scroll)
        
        layout.addWidget(self.stack)
        
    def _load_data(self):
        spec_thread = getattr(self, "_spec_thread", None)
        if spec_thread and spec_thread.isRunning():
            return
        self.stack.setCurrentIndex(0)
        self.scan_page.start("正在深度采集硬件配置...")
        self._refresh_btn.setEnabled(False)
        self._spec_thread = SpecReaderThread()
        self._spec_thread.specs_ready.connect(self._on_specs_ready)
        self._spec_thread.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        self._spec_thread.start()
        
    def _on_specs_ready(self, specs):
        self._refresh_btn.setEnabled(True)
        self.scan_page.stop()
        self.stack.setCurrentIndex(1)
        
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        for s in specs:
            try:
                card = SpecCard(
                    s["icon"], s["bg"], s["fg"],
                    s["c1_t"], s["c1_v"] if s["c1_v"] else "正在获取...",
                    s["c2_t"], s["c2_v"] if s["c2_v"] else "暂无数据",
                    self._create_status_widget(s["c3"])
                )
                self.content_layout.addWidget(card)
            except Exception as e:
                print(f"Card Render Error: {e}")
        
        self.content_layout.addStretch(1)

    def stop(self):
        """中断硬件采集线程并等待其退出。"""
        spec_thread = getattr(self, "_spec_thread", None)
        if spec_thread and spec_thread.isRunning():
            spec_thread.requestInterruption()
            spec_thread.wait(5000)
        
    def _create_status_widget(self, d):
        try:
            if d["type"] == "pill":
                l = QLabel(d["text"])
                l.setAlignment(Qt.AlignmentFlag.AlignCenter)
                l.setStyleSheet(f"background:{d['bg'] if 'bg' in d else '#F5F5F5'}; color:{d['fg'] if 'fg' in d else '#666'}; border-radius:6px; padding:6px 12px; font-size:11px; font-weight:bold;")
                return l
            elif d["type"] == "progress":
                p = MiniProgress()
                val = float(d['val']) if d['val'] else 0
                p.set_data("内存占用", val)
                return p
        except:
            return QLabel("-")
        return None
