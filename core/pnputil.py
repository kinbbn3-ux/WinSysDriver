# -*- coding: utf-8 -*-
"""PnPUtil 调用和输出解析。"""

from dataclasses import dataclass
import os
import re
import subprocess


RETURN_CODE_SUCCESS = 0
RETURN_CODE_REBOOT_REQUIRED = 3010
RETURN_CODE_REBOOT_INITIATED = 1641

_SUCCESS_CODES = {
    RETURN_CODE_SUCCESS,
    RETURN_CODE_REBOOT_REQUIRED,
    RETURN_CODE_REBOOT_INITIATED,
}


@dataclass(frozen=True)
class PnPUtilResult:
    """单次 pnputil 调用的结果。"""

    return_code: int
    stdout: str
    stderr: str
    command: tuple[str, ...]

    @property
    def output(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part).strip()

    @property
    def succeeded(self) -> bool:
        return self.return_code in _SUCCESS_CODES and not has_explicit_failure(self.output)


def run_add_driver(inf_path: str, timeout: int) -> PnPUtilResult:
    """添加并安装一个 INF，兼容新旧版本 PnPUtil 参数。"""
    working_directory = os.path.dirname(os.path.abspath(inf_path))
    inf_name = os.path.basename(inf_path)
    commands = (
        ("pnputil.exe", "/add-driver", inf_name, "/install"),
        ("pnputil.exe", "/i", "/a", inf_name),
    )

    last_result: PnPUtilResult | None = None
    for index, command in enumerate(commands):
        last_result = _run_command(command, working_directory, timeout)
        if index == 0 and not _needs_legacy_syntax(last_result):
            break
        if last_result.succeeded:
            break

    assert last_result is not None
    return last_result


def parse_package_count(output: str, kind: str) -> int | None:
    """解析 PnPUtil 的添加/安装数量，无法识别时返回 None。"""
    if kind == "total":
        labels = (
            r"total\s+driver\s+packages",
            r"驱动程序包总数",
            r"驱动程序包总计",
            r"驱动包总数",
        )
    elif kind == "added":
        labels = (
            r"added\s+driver\s+packages",
            r"successfully\s+added\s+driver\s+packages",
            r"添加的驱动程序包",
            r"成功添加的驱动程序包",
            r"已添加的驱动程序包",
            r"添加驱动包",
        )
    else:
        raise ValueError(f"未知数量类型: {kind}")

    label_pattern = "|".join(labels)
    match = re.search(
        rf"(?im)^\s*(?:{label_pattern})\s*[:：]\s*(\d+)\s*$",
        output,
    )
    return int(match.group(1)) if match else None


def has_explicit_failure(output: str) -> bool:
    """识别 PnPUtil 已明确报告失败的输出。"""
    failure_patterns = (
        r"failed",
        r"failure",
        r"error",
        r"失败",
        r"错误",
        r"无法",
        r"未能",
    )
    return any(re.search(pattern, output, re.IGNORECASE) for pattern in failure_patterns)


def _needs_legacy_syntax(result: PnPUtilResult) -> bool:
    """只在参数不受支持时回退，避免失败安装被无意义地执行两次。"""
    if result.return_code in (87, 9009):
        return True
    output = result.output.lower()
    return any(
        marker in output
        for marker in (
            "unknown option",
            "invalid option",
            "unrecognized option",
            "未知选项",
            "无效参数",
        )
    )


def _run_command(
    command: tuple[str, ...], working_directory: str, timeout: int
) -> PnPUtilResult:
    process = subprocess.run(
        list(command),
        cwd=working_directory,
        capture_output=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return PnPUtilResult(
        return_code=process.returncode,
        stdout=_decode_output(process.stdout),
        stderr=_decode_output(process.stderr),
        command=command,
    )


def _decode_output(value: bytes | str | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    for encoding in ("utf-8", "gb18030", "cp1252"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode(errors="replace")
