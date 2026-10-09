# -*- coding: utf-8 -*-
"""
安装管理器

在子线程中执行驱动的静默安装，通过 Signal/Slot 与 UI 通信。
支持安装进度追踪、自动重试、重启检测和暂停/取消控制。
"""

import os
import subprocess
import time
from typing import Optional

from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition

from models.driver_info import DriverInfo, InstallStatus, InstallerType
from core.driver_package import stage_inf_package, verify_driver_package
from core.pnputil import (
    RETURN_CODE_REBOOT_INITIATED as PNPUTIL_REBOOT_INITIATED,
    RETURN_CODE_REBOOT_REQUIRED as PNPUTIL_REBOOT_REQUIRED,
    run_add_driver,
)
from utils.logger import get_logger

logger = get_logger("InstallManager")

# Windows 安装程序返回码含义
RETURN_CODE_SUCCESS = 0
RETURN_CODE_REBOOT_REQUIRED = 3010
RETURN_CODE_REBOOT_INITIATED = 1641


class InstallManager(QThread):
    """
    驱动安装管理器（子线程）

    职责：
    1. 按顺序逐个执行驱动程序的静默安装
    2. 处理返回码（成功/失败/需重启）
    3. 失败时自动重试一次
    4. 支持暂停/继续/取消操作
    5. 通过信号实时通知 UI 层安装进度
    """

    # === 信号定义 ===
    # 安装进度更新：(当前索引, 总数, 当前驱动信息)
    progress_updated = Signal(int, int, DriverInfo)
    # 单个驱动安装完成：(驱动信息, 是否成功, 消息)
    install_finished = Signal(DriverInfo, bool, str)
    # 检测到需要重启：(驱动信息, 已完成列表)
    reboot_required = Signal(DriverInfo, list)
    # 全部安装完成：(结果列表)
    all_completed = Signal(list)
    cancelled = Signal()
    # 安装出错：(错误信息)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drivers: list[DriverInfo] = []
        self._start_index: int = 0
        self._is_cancelled = False
        self._is_paused = False
        self._mutex = QMutex()
        self._pause_condition = QWaitCondition()
        self._install_timeout = 600  # 单个驱动安装超时时间（秒）
        self._enforce_signature_check = True

    def set_drivers(self, drivers: list[DriverInfo], start_index: int = 0):
        """
        设置待安装的驱动列表

        Args:
            drivers: 驱动信息列表（已排序）
            start_index: 起始索引（用于会话恢复）
        """
        self._drivers = drivers
        self._start_index = start_index
        self._is_cancelled = False
        self._is_paused = False

    def set_signature_check_enabled(self, enabled: bool):
        """设置是否在安装前强制要求驱动数字签名有效"""
        self._enforce_signature_check = enabled

    def pause(self):
        """暂停安装"""
        self._mutex.lock()
        self._is_paused = True
        self._mutex.unlock()
        logger.info("安装已暂停")

    def resume(self):
        """继续安装"""
        self._mutex.lock()
        self._is_paused = False
        self._pause_condition.wakeAll()
        self._mutex.unlock()
        logger.info("安装已继续")

    def cancel(self):
        """取消安装"""
        self._is_cancelled = True
        # 如果正在暂停中，先唤醒线程再取消
        if self._is_paused:
            self.resume()
        logger.info("安装已取消")

    def run(self):
        """线程主体：逐个安装驱动"""
        total = len(self._drivers)
        completed_drivers: list[DriverInfo] = []

        logger.info(f"开始安装，共 {total} 个驱动，从索引 {self._start_index} 开始")

        for i in range(self._start_index, total):
            # 检查取消状态
            if self._is_cancelled:
                logger.info("安装已被用户取消")
                break

            # 检查暂停状态
            self._mutex.lock()
            while self._is_paused and not self._is_cancelled:
                self._pause_condition.wait(self._mutex)
            self._mutex.unlock()

            if self._is_cancelled:
                break

            driver = self._drivers[i]

            # 跳过未勾选的驱动
            if not driver.enabled:
                driver.status = InstallStatus.SKIPPED
                logger.info(f"[{i + 1}/{total}] 跳过（未勾选）: {driver.name}")
                completed_drivers.append(driver)
                continue

            # 发射进度信号
            driver.status = InstallStatus.INSTALLING
            self.progress_updated.emit(i + 1, total, driver)
            logger.info(f"[{i + 1}/{total}] 正在安装: {driver.name}")
            logger.info(f"  路径: {driver.file_path}")
            logger.info(f"  参数: {' '.join(driver.silent_args)}")

            # 执行安装（含重试逻辑）
            success, message, return_code = self._execute_install(driver)
            driver.return_code = return_code

            if return_code in (RETURN_CODE_REBOOT_REQUIRED, RETURN_CODE_REBOOT_INITIATED):
                # 需要重启
                driver.status = InstallStatus.REBOOT_NEEDED
                completed_drivers.append(driver)
                logger.warning(f"  → 需要重启（返回码: {return_code}）")
                self.install_finished.emit(driver, True, "安装成功，需要重启")
                self.reboot_required.emit(driver, completed_drivers.copy())
                return  # 中断安装流程，等待重启

            elif success:
                driver.status = InstallStatus.SUCCESS
                driver.error_message = ""
                logger.info(f"  → 安装成功")
                self.install_finished.emit(driver, True, "安装成功")
            else:
                driver.status = InstallStatus.FAILED
                driver.error_message = message
                logger.error(f"  → 安装失败: {message}")
                self.install_finished.emit(driver, False, message)

            completed_drivers.append(driver)

            # 安装间隔（给系统一点缓冲时间）
            time.sleep(1)

        if self._is_cancelled:
            self.cancelled.emit()
            return

        self.all_completed.emit(self._drivers)
        logger.info("=" * 40)
        logger.info("安装全部完成")
        self._log_summary()

    def _execute_install(
        self, driver: DriverInfo, is_retry: bool = False
    ) -> tuple[bool, str, Optional[int]]:
        """
        执行单个驱动的静默安装

        Args:
            driver: 驱动信息
            is_retry: 是否为重试

        Returns:
            (是否成功, 消息, 返回码) 元组
        """
        if self._enforce_signature_check:
            is_signed, signer = verify_driver_package(
                driver.file_path, driver.installer_type
            )
            driver.is_signed = is_signed
            if signer:
                driver.signer = signer
            if not is_signed:
                logger.warning(f"  → 已阻止未通过签名校验的驱动: {driver.name}")
                return False, "数字签名无效或缺失，安全策略已阻止安装", None

        if driver.installer_type in {
            InstallerType.INF,
            InstallerType.CAB,
            InstallerType.ZIP,
        }:
            return self._install_inf_package(driver, is_retry)
        if driver.installer_type == InstallerType.MSI:
            cmd = ["msiexec", "/i", driver.file_path, "/qn", "/norestart"]
        else:
            cmd = [driver.file_path] + driver.silent_args
        retry_label = "（重试）" if is_retry else ""

        try:
            logger.debug(f"  执行命令{retry_label}: {' '.join(cmd)}")

            process = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self._install_timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            return_code = process.returncode

            if return_code == RETURN_CODE_SUCCESS:
                return True, "", return_code

            elif return_code in (RETURN_CODE_REBOOT_REQUIRED, RETURN_CODE_REBOOT_INITIATED):
                return True, "需要重启", return_code

            else:
                error_msg = f"返回码: {return_code}"
                stderr = process.stderr.decode("utf-8", errors="ignore").strip()
                if stderr:
                    error_msg += f" | 错误输出: {stderr[:200]}"

                # 如果不是重试，则自动重试一次
                if not is_retry:
                    logger.warning(f"  安装失败（{error_msg}），正在重试...")
                    time.sleep(2)  # 等待 2 秒后重试
                    return self._execute_install(driver, is_retry=True)

                return False, error_msg, return_code

        except subprocess.TimeoutExpired:
            error_msg = f"安装超时（超过 {self._install_timeout} 秒）"
            if not is_retry:
                logger.warning(f"  {error_msg}，正在重试...")
                time.sleep(2)
                return self._execute_install(driver, is_retry=True)
            return False, error_msg, None

        except FileNotFoundError:
            return False, f"文件未找到: {driver.file_path}", None

        except PermissionError:
            return False, "权限不足，请以管理员身份运行", None

        except Exception as e:
            error_msg = f"未知异常: {str(e)}"
            if not is_retry:
                logger.warning(f"  {error_msg}，正在重试...")
                time.sleep(2)
                return self._execute_install(driver, is_retry=True)
            return False, error_msg, None

    def _install_inf_package(
        self, driver: DriverInfo, is_retry: bool = False
    ) -> tuple[bool, str, Optional[int]]:
        """暂存传统驱动包并使用 pnputil 安装其中的 INF 文件。"""
        try:
            with stage_inf_package(driver.file_path, driver.installer_type) as (_, inf_files):
                if not inf_files:
                    return False, "驱动包中未找到 INF 文件", None

                succeeded = 0
                reboot_code: Optional[int] = None
                errors = []
                for inf_file in inf_files:
                    result = run_add_driver(inf_file, self._install_timeout)
                    output = result.output
                    logger.info(
                        "  pnputil: %s\n%s",
                        " ".join(result.command),
                        output[:2000] if output else "(无输出)",
                    )
                    if result.succeeded:
                        succeeded += 1
                        if result.return_code in (
                            PNPUTIL_REBOOT_REQUIRED,
                            PNPUTIL_REBOOT_INITIATED,
                        ):
                            reboot_code = result.return_code
                    else:
                        errors.append(
                            f"{os.path.basename(inf_file)}: "
                            f"{output[:400] or f'返回码: {result.return_code}'}"
                        )

                if errors:
                    partial = f"部分成功（{succeeded}/{len(inf_files)}）: " if succeeded else ""
                    return False, partial + "；".join(errors), None
                if succeeded == len(inf_files):
                    return True, f"已安装 {succeeded} 个 INF 驱动包", reboot_code or RETURN_CODE_SUCCESS
                return False, "pnputil 未报告任何已安装的驱动包", None
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            message = "系统缺少 pnputil/expand 工具或驱动包处理超时"
            if isinstance(error, subprocess.TimeoutExpired):
                message = "驱动包安装超时"
            return False, message, None
        except Exception as error:
            if not is_retry:
                time.sleep(2)
                return self._install_inf_package(driver, is_retry=True)
            return False, f"驱动包安装异常: {error}", None

    def _log_summary(self):
        """输出安装结果汇总"""
        success = sum(1 for d in self._drivers if d.status == InstallStatus.SUCCESS)
        failed = sum(1 for d in self._drivers if d.status == InstallStatus.FAILED)
        skipped = sum(1 for d in self._drivers if d.status == InstallStatus.SKIPPED)
        reboot = sum(1 for d in self._drivers if d.status == InstallStatus.REBOOT_NEEDED)

        logger.info(f"  成功: {success}")
        logger.info(f"  失败: {failed}")
        logger.info(f"  跳过: {skipped}")
        logger.info(f"  需重启: {reboot}")

        if failed > 0:
            logger.info("失败的驱动:")
            for d in self._drivers:
                if d.status == InstallStatus.FAILED:
                    logger.info(f"  - {d.name}: {d.error_message}")
