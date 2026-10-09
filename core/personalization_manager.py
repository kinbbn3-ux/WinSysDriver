# -*- coding: utf-8 -*-
"""
个性化配置管理器 - 软件安装后的自动化配置

扩展支持：
- FileLocator: 禁用搜索历史记录
- PotPlayer: 全格式关联、禁用自动更新、禁用侧边栏
- 7-Zip / Everything / 搜狗
"""

import os
import subprocess
import winreg
from utils.logger import get_logger

logger = get_logger("PersonalizationManager")

def apply_registry_tweak(hkey, key_path: str, value_name: str, value_data, value_type=winreg.REG_SZ):
    """通用注册表写入工具"""
    try:
        key = winreg.CreateKeyEx(hkey, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, value_name, 0, value_type, value_data)
        winreg.CloseKey(key)
        logger.info(f"  [优化] 注册表写入成功: {key_path}\\{value_name}")
        return True
    except Exception as e:
        logger.error(f"  [优化] 注册表写入失败: {e}")
        return False

def run_ps_command(command: str):
    """执行 PowerShell 命令"""
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", command], 
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except:
        return False

# ── FileLocator: 禁用历史记录 ──────────────────────────────────────────
def tweak_filelocator():
    """FileLocator 不保留搜索记录"""
    # 兼容 Pro 和 Lite 版本
    paths = [
        r"Software\Mythicsoft\FileLocatorPro\Settings",
        r"Software\Mythicsoft\FileLocatorLite\Settings"
    ]
    for path in paths:
        apply_registry_tweak(winreg.HKEY_CURRENT_USER, path, "SaveHistory", 0, winreg.REG_DWORD)
        apply_registry_tweak(winreg.HKEY_CURRENT_USER, path, "HistoryMax", 0, winreg.REG_DWORD)
    logger.info("  [优化] FileLocator 历史记录已禁用")

# ── PotPlayer: 全格式关联与优化 ─────────────────────────────────────────
_POTPLAYER_ASSOCIATE_PS = r'''
$potPath = "${env:ProgramFiles}\DAUM\PotPlayer\PotPlayerMini64.exe"
if (-not (Test-Path $potPath)) { $potPath = "${env:ProgramFiles(x86)}\DAUM\PotPlayer\PotPlayerMini.exe" }
if (Test-Path $potPath) {
    $videoExts = @(".mp4", ".mkv", ".avi", ".flv", ".rmvb", ".mov", ".wmv", ".3gp", ".ts", ".m2ts", ".webm")
    foreach ($ext in $videoExts) {
        $path = "HKLM:\SOFTWARE\Classes\$ext"
        if (-not (Test-Path $path)) { New-Item $path -Force | Out-Null }
        Set-ItemProperty $path -Name "(Default)" -Value "PotPlayer64.File"
    }
    # 刷新 Shell 图标
    $code = '[DllImport("shell32.dll")] public static extern void SHChangeNotify(uint e, uint f, IntPtr d1, IntPtr d2);'
    Add-Type -MemberDefinition $code -Name "Shell32" -Namespace "Win32"
    [Win32.Shell32]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)
}
'''

def tweak_potplayer():
    """PotPlayer 进阶优化"""
    # 1. 执行全格式关联 (PowerShell)
    run_ps_command(_POTPLAYER_ASSOCIATE_PS)
    
    # 2. 禁用自动更新与侧边栏 (注册表)
    pot_path = r"Software\DAUM\PotPlayer64"
    tweaks = [
        ("AutoUpdate", 0, winreg.REG_DWORD),       # 禁用自动更新
        ("ShowTVLive", 0, winreg.REG_DWORD),       # 禁用右侧直播列表
        ("RememberVideoPos", 1, winreg.REG_DWORD), # 开启记忆播放位置
    ]
    for name, val, vtype in tweaks:
        apply_registry_tweak(winreg.HKEY_CURRENT_USER, pot_path, name, val, vtype)
    logger.info("  [优化] PotPlayer 全格式关联及自动更新已禁用")

# ── 7-Zip / Everything / 搜狗 已有配置 (略作整合) ────────────────────────
_7ZIP_ASSOCIATE_PS = r'''
$7zPath = "${env:ProgramFiles}\7-Zip\7zG.exe"
if (-not (Test-Path $7zPath)) { $7zPath = "${env:ProgramFiles(x86)}\7-Zip\7zG.exe" }
if (Test-Path $7zPath) {
    $exts = @(".7z", ".zip", ".rar", ".tar", ".gz", ".iso", ".cab", ".bz2")
    foreach ($ext in $exts) {
        $path = "HKLM:\SOFTWARE\Classes\$ext"
        if (-not (Test-Path $path)) { New-Item $path -Force | Out-Null }
        Set-ItemProperty $path -Name "(Default)" -Value "7-Zip.Archive"
    }
    $code = '[DllImport("shell32.dll")] public static extern void SHChangeNotify(uint e, uint f, IntPtr d1, IntPtr d2);'
    Add-Type -MemberDefinition $code -Name "Shell32" -Namespace "Win32"
    [Win32.Shell32]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)
}
'''

def tweak_everything():
    appdata = os.environ.get("APPDATA")
    ini_path = os.path.join(appdata, "Everything", "Everything.ini")
    os.makedirs(os.path.dirname(ini_path), exist_ok=True)
    settings = {"run_as_admin": "1", "show_tray_icon": "1", "check_for_updates_on_startup": "0"}
    try:
        new_lines = []
        applied = set()
        if os.path.exists(ini_path):
            with open(ini_path, "r", encoding="utf-16") as f:
                for line in f:
                    found = False
                    for k, v in settings.items():
                        if line.startswith(f"{k}="):
                            new_lines.append(f"{k}={v}\n"); applied.add(k); found = True; break
                    if not found: new_lines.append(line)
        for k, v in settings.items():
            if k not in applied: new_lines.append(f"{k}={v}\n")
        with open(ini_path, "w", encoding="utf-16") as f: f.writelines(new_lines)
    except: pass

def tweak_sogou():
    apply_registry_tweak(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\SogouNews.exe", "Debugger", "ntsd -d")
    sogou_path = r"Software\SogouInput"
    for name in ["ShowNews", "ShowMedal", "ShowSkinPopup", "UpdateRemind"]:
        apply_registry_tweak(winreg.HKEY_CURRENT_USER, sogou_path, name, 0, winreg.REG_DWORD)

# ── 最终映射字典 ──────────────────────────────────────────────────────────
SOFTWARE_TWEAKS = {
    "7-Zip": [lambda: run_ps_command(_7ZIP_ASSOCIATE_PS)],
    "Everything": [tweak_everything],
    "Sogou": [tweak_sogou],
    "搜狗": [tweak_sogou],
    "FileLocator": [tweak_filelocator],
    "PotPlayer": [tweak_potplayer],
}

def apply_tweaks_for_package(pkg_name: str):
    """匹配并执行优化"""
    for key, tweaks in SOFTWARE_TWEAKS.items():
        if key.lower() in pkg_name.lower():
            logger.info(f"正在为 {pkg_name} 执行个性化优化...")
            for tweak in tweaks:
                try: tweak()
                except Exception as e: logger.error(f"  执行优化项失败: {e}")
