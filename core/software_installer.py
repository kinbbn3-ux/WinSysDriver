# -*- coding: utf-8 -*-
"""
软件安装执行引擎

在子线程中按队列顺序执行软件包的静默安装。
支持 EXE / MSI / ZIP / Office 四种安装模式，
超时保护、自动重试（一次）、暂停/继续/取消/跳过控制，
以及详细的安装日志输出。
"""

import os
import subprocess
import zipfile
import time
import logging
from typing import Optional
from datetime import datetime

from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition

from models.package_info import PackageInfo, SoftwareInstallerType, PackageType
from models.driver_info import InstallStatus
from utils.logger import get_logger

logger = get_logger("SoftwareInstaller")

# 安装成功的返回码
_SUCCESS_CODES = {0}
# 需要重启的返回码（部分 EXE 安装后会返回 3010）
_REBOOT_CODES = {3010, 1641}


def _get_log_dir() -> str:
    """获取日志输出目录（项目 logs/ 子目录）"""
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
    os.makedirs(base, exist_ok=True)
    return base


class SoftwareInstaller(QThread):
    """
    软件安装引擎（子线程）

    信号（与 InstallManager 命名对齐）：
      progress_updated(current, total, pkg)  → 实时安装进度
      install_finished(pkg, success, msg)    → 单个包安装完成
      all_completed(list[pkg])               → 全部完成
      error_occurred(str)                    → 全局错误
    """

    progress_updated = Signal(int, int, object)    # (current, total, PackageInfo)
    install_finished = Signal(object, bool, str)   # (PackageInfo, success, message)
    all_completed    = Signal(list)                # List[PackageInfo]
    cancelled        = Signal()
    error_occurred   = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._packages: list[PackageInfo] = []
        self._is_cancelled = False
        self._is_paused = False
        self._skip_current = False
        self._mutex = QMutex()
        self._pause_condition = QWaitCondition()
        self._file_logger: Optional[logging.Logger] = None
        self._enforce_signature_check = True

    def set_packages(self, packages: list[PackageInfo]):
        """设置待安装的软件包列表"""
        self._packages = packages
        self._is_cancelled = False
        self._is_paused = False
        self._skip_current = False

    def set_signature_check_enabled(self, enabled: bool):
        """设置是否在安装前强制执行软件包数字签名安全策略"""
        self._enforce_signature_check = enabled

    # ── 控制接口 ─────────────────────────────────────────────────────────
    def pause(self):
        self._mutex.lock(); self._is_paused = True; self._mutex.unlock()
        logger.info("软件安装已暂停")

    def resume(self):
        self._mutex.lock(); self._is_paused = False
        self._pause_condition.wakeAll(); self._mutex.unlock()
        logger.info("软件安装已继续")

    def cancel(self):
        self._is_cancelled = True
        if self._is_paused:
            self.resume()
        logger.info("软件安装已取消")

    def skip(self):
        """跳过当前正在安装的包"""
        self._skip_current = True
        logger.info("跳过当前安装包")

    # ── 线程主体 ──────────────────────────────────────────────────────────
    def run(self):
        """按顺序执行所有软件包的安装"""
        self._setup_file_logger()
        total = len(self._packages)
        self._file_logger.info(f"{'='*60}")
        self._file_logger.info(f"软件批量安装开始 — {datetime.now():%Y-%m-%d %H:%M:%S}")
        self._file_logger.info(f"共 {total} 个安装包")
        self._file_logger.info(f"{'='*60}")

        completed: list[PackageInfo] = []

        for i, pkg in enumerate(self._packages):
            if self._is_cancelled:
                break

            # 暂停等待
            self._mutex.lock()
            while self._is_paused and not self._is_cancelled:
                self._pause_condition.wait(self._mutex)
            self._mutex.unlock()

            if self._is_cancelled:
                break

            # 跳过未勾选
            if not pkg.enabled:
                pkg.status = InstallStatus.SKIPPED
                completed.append(pkg)
                self._file_logger.info(f"[{i+1}/{total}] SKIP (未勾选): {pkg.name}")
                continue

            # 发射进度
            self._skip_current = False
            pkg.status = InstallStatus.INSTALLING
            self.progress_updated.emit(i + 1, total, pkg)
            self._file_logger.info(f"\n[{i+1}/{total}] 开始安装: {pkg.name}")
            self._file_logger.info(f"  路径: {pkg.file_path}")
            self._file_logger.info(f"  类型: {pkg.installer_type.value}")
            self._file_logger.info(f"  参数: {pkg.get_effective_args()}")
            self._file_logger.info(f"  超时: {pkg.get_timeout()}s")

            if pkg.installer_type == SoftwareInstallerType.PORTABLE_APP:
                pkg.status = InstallStatus.SKIPPED
                pkg.error_message = ""
                self.install_finished.emit(pkg, True, "便携软件无需安装，已跳过")
                completed.append(pkg)
                continue

            from models.package_info import SigStatus
            if self._enforce_signature_check and pkg.sig_status in (SigStatus.TAMPERED, SigStatus.ERROR):
                success, message, code = False, "签名损坏、无法验证或不匹配，安全策略已阻止安装", None
            else:
                success, message, code = self._execute(pkg)
            
            pkg.return_code = code

            if success:
                pkg.status = InstallStatus.SUCCESS
                pkg.error_message = ""
                self._file_logger.info(f"  ✅ 成功 (返回码: {code})")
                
                # --- 新增：自动化个性化设置挂钩 ---
                try:
                    from core.personalization_manager import apply_tweaks_for_package
                    apply_tweaks_for_package(pkg.name)
                except Exception as e:
                    logger.warning(f"  [优化错误] 执行个性化设置失败: {e}")
            else:
                pkg.status = InstallStatus.FAILED
                pkg.error_message = message
                self._file_logger.error(f"  ❌ 失败: {message} (返回码: {code})")

            self.install_finished.emit(pkg, success, message)
            completed.append(pkg)
            time.sleep(0.5)  # 给系统短暂缓冲

        self._write_summary(completed)
        if self._is_cancelled:
            self.cancelled.emit()
            return
        self.all_completed.emit(self._packages)

    # ── 安装分派 ─────────────────────────────────────────────────────────
    def _execute(self, pkg: PackageInfo, is_retry=False) -> tuple[bool, str, Optional[int]]:
        """根据安装类型分派到对应的安装方法"""
        try:
            if pkg.installer_type == SoftwareInstallerType.ZIP:
                return self._install_zip(pkg)
            elif pkg.installer_type == SoftwareInstallerType.MSI:
                return self._install_msi(pkg, is_retry)
            elif pkg.installer_type == SoftwareInstallerType.OFFICE_ODT:
                return self._install_office(pkg, is_retry)
            elif pkg.installer_type == SoftwareInstallerType.ISO_IMAGE:
                return self._install_iso(pkg, is_retry)
            else:
                return self._install_exe(pkg, is_retry)

        except Exception as e:
            msg = f"未知异常: {str(e)}"
            logger.exception(msg)
            if not is_retry:
                time.sleep(2)
                return self._execute(pkg, is_retry=True)
            return False, msg, None

    # ── ZIP 解压 ──────────────────────────────────────────────────────────
    def _install_zip(self, pkg: PackageInfo) -> tuple[bool, str, Optional[int]]:
        """解压 ZIP 包到指定目录，可选加入 PATH"""
        extract_to = pkg.zip_extract_path or os.path.join("C:\\Tools", pkg.name)
        self._file_logger.info(f"  [ZIP] 解压到: {extract_to}")

        try:
            os.makedirs(extract_to, exist_ok=True)
            with zipfile.ZipFile(pkg.file_path, 'r') as zf:
                # 防护 Zip Slip: 彻底阻断利用相对路径漏洞覆写系统文件的危险行为
                resolved_extract_to = os.path.realpath(extract_to)
                for member in zf.infolist():
                    member_path = os.path.realpath(os.path.join(resolved_extract_to, member.filename))
                    try:
                        inside_extract_root = os.path.commonpath(
                            [resolved_extract_to, member_path]
                        ) == resolved_extract_to
                    except ValueError:
                        inside_extract_root = False
                    if not inside_extract_root:
                        return False, f"终止安装！发现恶意 ZIP 路径逃逸尝试 ({member.filename})", None
                    zf.extract(member, extract_to)

            if pkg.add_to_path:
                self._add_to_system_path(extract_to)
                self._file_logger.info(f"  [ZIP] 已加入 PATH: {extract_to}")

            # ZIP 智能入口识别与快捷方式创建
            self._find_zip_entrypoint(pkg, extract_to)
            if pkg.create_shortcut and pkg.zip_entrypoint:
                self._create_shortcut(pkg.zip_entrypoint, pkg.name)
                self._file_logger.info(f"  [ZIP] 已创建桌面快捷方式: {pkg.zip_entrypoint}")

            return True, f"解压成功: {extract_to}", 0

        except zipfile.BadZipFile:
            return False, "ZIP 文件损坏", None
        except PermissionError:
            return False, f"权限不足，无法写入: {extract_to}", None
        except Exception as e:
            return False, str(e), None

    # ── MSI 安装 ──────────────────────────────────────────────────────────
    def _install_msi(self, pkg: PackageInfo, is_retry=False) -> tuple[bool, str, Optional[int]]:
        """使用 msiexec 执行 MSI 安装"""
        log_path = os.path.join(_get_log_dir(), f"{pkg.name}_msi.log")
        cmd = [
            "msiexec", "/i", pkg.file_path,
            "/qn", "/norestart",
            f"/log", log_path
        ]
        self._file_logger.info(f"  [MSI] 命令: {' '.join(cmd)}")
        return self._run_subprocess(pkg, cmd, is_retry)

    # ── EXE 安装 ──────────────────────────────────────────────────────────
    def _install_exe(self, pkg: PackageInfo, is_retry=False) -> tuple[bool, str, Optional[int]]:
        """执行 EXE 安装包（带智能参数回退与轮询尝试）"""
        args = pkg.get_effective_args()
        
        # 默认回退：如果没参数，先尝试 /S
        if not args:
            args = ["/S"]

        self._file_logger.info(f"  [EXE] 尝试主参数安装: {' '.join(args)}")
        success, msg, code = self._run_subprocess(pkg, [pkg.file_path] + args, is_retry)

        # 核心逻辑：如果主参数安装失败（或超时），且非用户手动指定的，尝试“智能参数轮询”
        if not success and not pkg.user_override_args.strip() and not is_retry:
            # 定义一个常用静默参数池（根据行业通用标准排序）
            fallback_pool = [
                ["/silent", "/norestart"],
                ["/quiet", "/qn", "/norestart"],
                ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                ["-s"],
                ["--silent"]
            ]
            
            for extra_args in fallback_pool:
                self._file_logger.info(f"  [EXE] 主参数失败，正在尝试轮询静默参数: {' '.join(extra_args)}")
                s2, m2, c2 = self._run_subprocess(pkg, [pkg.file_path] + extra_args, is_retry=True)
                if s2:
                    return s2, f"参数轮询成功: {m2}", c2
        
        return success, msg, code

    # ── Office 安装 ───────────────────────────────────────────────────────
    def _install_office(self, pkg: PackageInfo, is_retry=False) -> tuple[bool, str, Optional[int]]:
        """
        执行 Office 离线安装：
        - 优先使用 configuration.xml 配置文件
        - 若无配置文件则以 /configure 静默安装
        """
        if pkg.office_config_path and os.path.isfile(pkg.office_config_path):
            cmd = [pkg.file_path, "/configure", pkg.office_config_path]
            self._file_logger.info(f"  [Office] 使用配置文件安装: {pkg.office_config_path}")
        else:
            cmd = [pkg.file_path, "/silent"]
            self._file_logger.info("  [Office] 无配置文件，使用 /silent 参数")

        self._file_logger.info(f"  [Office] 命令: {' '.join(cmd)}")
        return self._run_subprocess(pkg, cmd, is_retry)

    # ── ISO 挂载安装 ──────────────────────────────────────────────────────
    def _install_iso(self, pkg: PackageInfo, is_retry=False) -> tuple[bool, str, Optional[int]]:
        """
        处理 ISO 镜像安装：
        1. 挂载镜像并获取驱动器号
        2. 搜索挂载点根目录下的 setup.exe
        3. 识别 setup.exe 类型并执行
        4. 安装结束后卸载
        """
        self._file_logger.info(f"  [ISO] 正在挂载镜像: {pkg.file_path}")
        
        # 1. 尝试挂载
        drive_letter = self._mount_iso(pkg.file_path)
        if not drive_letter:
            return False, "挂载镜像失败，请确认镜像文件未损坏且具备管理员权限", None
        
        pkg.temp_mount_drive = drive_letter
        self._file_logger.info(f"  [ISO] 挂载成功，驱动器号: {drive_letter}")

        try:
            # 2. 寻找入口
            setup_path = os.path.join(drive_letter, "setup.exe")
            if not os.path.isfile(setup_path):
                # 兼容通用搜索
                setup_path = ""
                for root, _, files in os.walk(drive_letter):
                    if "setup.exe" in [f.lower() for f in files]:
                        setup_path = os.path.join(root, "setup.exe")
                        break
                    if len(root) > 5: # 仅搜索根目录
                        break

            if not setup_path:
                return False, f"在镜像 {drive_letter} 中未找到 setup.exe", None

            # 3. 识别镜像内部的安装包类型
            self._file_logger.info(f"  [ISO] 发现安装入口: {setup_path}")
            inner_pkg = PackageInfo(name=pkg.name, file_path=setup_path)
            from core.software_detector import SoftwareDetector
            inner_pkg = SoftwareDetector.detect(inner_pkg)
            
            # 手动填充配置路径（如果是在镜像里的 Office）
            if inner_pkg.installer_type == SoftwareInstallerType.OFFICE_ODT:
                config_path = SoftwareDetector.find_office_config(setup_path)
                if config_path:
                    inner_pkg.office_config_path = config_path
                    self._file_logger.info(f"  [ISO|Office] 找到配置文件: {config_path}")

            # 4. 执行内部安装
            if inner_pkg.installer_type == SoftwareInstallerType.OFFICE_ODT:
                success, msg, code = self._install_office(inner_pkg, is_retry)
            else:
                success, msg, code = self._install_exe(inner_pkg, is_retry)
            
            return success, msg, code

        finally:
            # 5. 卸载镜像
            self._file_logger.info(f"  [ISO] 正在卸载镜像: {drive_letter}")
            self._dismount_iso(pkg.file_path)
            pkg.temp_mount_drive = ""

    def _mount_iso(self, iso_path: str) -> Optional[str]:
        """使用 PowerShell 挂载 ISO 并返回盘符（如 'F:\'）"""
        ps_cmd = (
            f'$m = Mount-DiskImage -ImagePath "{iso_path}" -PassThru; '
            'if ($m) { ($m | Get-Volume).DriveLetter + ":" }'
        )
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
            drive = res.stdout.strip()
            if len(drive) >= 2 and drive[1] == ":":
                # 检查盘符是否真实存在且可访问
                drive_path = drive if drive.endswith("\\") else drive + "\\"
                if os.path.exists(drive_path):
                    return drive_path
            return None
        except:
            return None

    def _dismount_iso(self, iso_path: str):
        """使用 PowerShell 卸载磁盘镜像"""
        ps_cmd = f'Dismount-DiskImage -ImagePath "{iso_path}"'
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
        except:
            pass

    # ── subprocess 执行 ───────────────────────────────────────────────────
    def _run_subprocess(
        self, pkg: PackageInfo, cmd: list[str], is_retry: bool
    ) -> tuple[bool, str, Optional[int]]:
        """统一的子进程执行方法，含超时与返回码处理"""
        retry_label = "（重试）" if is_retry else ""

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            
            try:
                stdout_data, stderr_data = proc.communicate(timeout=pkg.get_timeout())
                code = proc.returncode
            except subprocess.TimeoutExpired:
                msg = f"安装超时（>{pkg.get_timeout()}s），正在强制猎杀遗留进程树..."
                self._file_logger.error(f"  {msg}")
                
                # Timeout 抛出后主动向下剿灭进程树，防止 msi 安装锁被后台残留持有
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], 
                                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    proc.communicate(timeout=5)  # 抽干管道
                except Exception as e:
                    self._file_logger.warning(f"  进程树清理失败: {e}")

                if not is_retry:
                    time.sleep(2)
                    return self._run_subprocess(pkg, cmd, is_retry=True)
                return False, msg, None

            # 写入 stderr 到日志（供调试）
            stderr_text = stderr_data.decode("utf-8", errors="ignore").strip()
            if stderr_text:
                self._file_logger.warning(f"  STDERR: {stderr_text[:500]}")

            stdout_text = stdout_data.decode("utf-8", errors="ignore").strip()
            if stdout_text:
                self._file_logger.debug(f"  STDOUT: {stdout_text[:500]}")

            if code in _SUCCESS_CODES or code in _REBOOT_CODES:
                return True, "安装成功", code

            msg = f"返回码: {code}"
            if stderr_text:
                msg += f" | {stderr_text[:200]}"

            if not is_retry:
                self._file_logger.warning(f"  失败{retry_label}，2 秒后重试...")
                time.sleep(2)
                return self._run_subprocess(pkg, cmd, is_retry=True)

            return False, msg, code

        except FileNotFoundError:
            return False, f"文件不存在: {cmd[0]}", None

        except OSError as e:
            if getattr(e, 'winerror', None) == 740:
                self._file_logger.error(f"  [UAC错误] {cmd[0]} 需要管理员权限启动 (WinError 740)")
                return False, "需要以管理员权限重启 DriverInstaller 方可安装", None
            return False, f"系统调用异常: {e}", None

        except PermissionError:
            return False, "权限不足，请以管理员身份运行", None

    # ── 工具方法 ──────────────────────────────────────────────────────────
    @staticmethod
    def _add_to_system_path(directory: str):
        """将目录添加到用户级 PATH 环境变量（需要 winreg）"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Environment",
                0, winreg.KEY_ALL_ACCESS
            )
            current_path, _ = winreg.QueryValueEx(key, "PATH")
            if directory.lower() not in current_path.lower():
                new_path = current_path + ";" + directory
                winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
            winreg.CloseKey(key)
        except Exception as e:
            logger.warning(f"加入 PATH 失败: {e}")

    def _setup_file_logger(self):
        """创建本次安装会话专属的日志文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(_get_log_dir(), f"software_install_{timestamp}.log")

        self._file_logger = logging.getLogger(f"SoftwareInstall.{timestamp}")
        self._file_logger.setLevel(logging.DEBUG)
        if not self._file_logger.handlers:
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)-5s] %(message)s",
                datefmt="%H:%M:%S"
            ))
            self._file_logger.addHandler(fh)

        logger.info(f"安装日志保存至: {log_path}")

    def _write_summary(self, packages: list[PackageInfo]):
        """写入安装结果汇总"""
        success = sum(1 for p in packages if p.status == InstallStatus.SUCCESS)
        failed  = sum(1 for p in packages if p.status == InstallStatus.FAILED)
        skipped = sum(1 for p in packages if p.status == InstallStatus.SKIPPED)

        summary = [
            f"\n{'='*60}",
            f"安装完成汇总 — {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"  ✅ 成功: {success}",
            f"  ❌ 失败: {failed}",
            f"  ⏭ 跳过: {skipped}",
        ]

        if failed > 0:
            summary.append("\n失败项明细:")
            for p in packages:
                if p.status == InstallStatus.FAILED:
                    summary.append(f"  - {p.name}: {p.error_message} (返回码: {p.return_code})")

        summary.append(f"{'='*60}")
        for line in summary:
            self._file_logger.info(line)

    def _find_zip_entrypoint(self, pkg: PackageInfo, extract_to: str):
        """寻找 ZIP 解压包内的合理启动程序"""
        candidate_exes = []
        for root, _, files in os.walk(extract_to):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                name_lower = file.lower()
                if ext == ".exe" and not any(kw in name_lower for kw in ["unins", "setup", "update"]):
                    full_path = os.path.join(root, file)
                    try:
                        size = os.path.getsize(full_path)
                        candidate_exes.append((full_path, file, size))
                    except:
                        pass
        
        if not candidate_exes:
            return

        import difflib
        
        # 启发式算分：越接近包名，分数越高，再加上大小的分数权重
        best_exe = None
        best_score = -1
        max_size = max([c[2] for c in candidate_exes]) if candidate_exes else 1

        for full_path, file_name, size in candidate_exes:
            similarity = difflib.SequenceMatcher(None, pkg.name.lower(), os.path.splitext(file_name)[0].lower()).ratio()
            size_score = size / max_size if max_size > 0 else 0
            # 综合得分：相似度为主，大小为辅
            score = similarity * 0.7 + size_score * 0.3
            if score > best_score:
                best_score = score
                best_exe = full_path

        if best_exe:
            pkg.zip_entrypoint = best_exe
            self._file_logger.info(f"  [ZIP] 智能识别入口程序: {best_exe}")

    def _create_shortcut(self, target_path: str, shortcut_name: str):
        """通过 Windows Script Host 创建桌面快捷方式"""
        try:
            import platform
            if platform.system() != "Windows":
                return
            
            # 使用 VBScript 编写快捷方式创建脚本来避免引入只在 Windows 有用的 pypiwi32 等库
            vbs_script = f'''
Set ws = CreateObject("WScript.Shell")
strDesktop = ws.SpecialFolders("Desktop")
Set shortcut = ws.CreateShortcut(strDesktop & "\\{shortcut_name}.lnk")
shortcut.TargetPath = "{target_path}"
shortcut.WorkingDirectory = "{os.path.dirname(target_path)}"
shortcut.Save
'''
            vbs_path = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "create_shortcut.vbs")
            with open(vbs_path, "w", encoding="gbk") as f:
                f.write(vbs_script)
            
            subprocess.run(["cscript", "//nologo", vbs_path], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                os.remove(vbs_path)
            except:
                pass
        except Exception as e:
            self._file_logger.warning(f"  [ZIP] 创建快捷方式失败: {e}")
