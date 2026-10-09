# -*- coding: utf-8 -*-
"""
数字签名核验模块 (批处理优化版)

通过一次性调用 PowerShell 管道对所有 EXE/MSI 进行批量获取状态，
彻底解决多文件下短时间内启动数百个 PowerShell 进程导致的性能灾难。
"""

import subprocess
import json
import base64
from models.package_info import SigStatus
from utils.logger import get_logger

logger = get_logger("SignatureChecker")

# 使用 Base64 传递路径以规避 PowerShell 特殊字符截断问题，且输出为 JSON 格式便于解析
_PS_BATCH_SCRIPT = """
$paths = '{b64_paths}';
$decoded = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($paths));
$fileList = $decoded -split "`n" | Where-Object {{ $_ -ne '' }};

$results = @();
foreach ($f in $fileList) {{
    try {{
        $sig = Get-AuthenticodeSignature -FilePath $f -ErrorAction SilentlyContinue;
        $status = if ($null -eq $sig) {{ "UnknownError" }} else {{ $sig.Status.ToString() }};
        $signer = "";
        
        if ($status -eq "Valid" -and $null -ne $sig.SignerCertificate) {{
            $signer = $sig.SignerCertificate.Subject;
        }}
        
        $results += @{{
            Path = $f;
            Status = $status;
            Signer = $signer;
        }};
    }} catch {{
        $results += @{{ Path = $f; Status = "UnknownError"; Signer = "" }};
    }}
}}

$results | ConvertTo-Json -Compress
"""

# PowerShell 状态值 → SigStatus 常量映射
_STATUS_MAP: dict[str, str] = {
    "Valid":                   SigStatus.VALID,
    "NotSigned":               SigStatus.NOT_SIGNED,
    "HashMismatch":            SigStatus.TAMPERED,
    "NotTrusted":              SigStatus.TAMPERED,
    "UnknownError":            SigStatus.ERROR,
    "Incompatible":            SigStatus.ERROR,
    "SignatureFormatError":    SigStatus.ERROR,
    "CertificateRevoked":      SigStatus.TAMPERED,
    "CertExpired":             SigStatus.TAMPERED,
}

_SKIP_EXTENSIONS = {".zip"}
_TIMEOUT_SEC = 30  # 给大批量扫描最多30秒超时


def batch_check_signatures(file_paths: list[str]) -> dict[str, tuple[str, str]]:
    """
    批量核验多个文件的 Authenticode 数字签名。

    Args:
        file_paths: 待核验的文件绝对路径列表

    Returns:
        dict: { "绝对路径": (sig_status, sig_signer) }
    """
    import os
    results: dict[str, tuple[str, str]] = {}
    
    # 过滤出不需要扫描的文件，直接填入默认值
    valid_paths = []
    for path in file_paths:
        ext = os.path.splitext(path)[1].lower()
        if ext in _SKIP_EXTENSIONS:
            results[path] = (SigStatus.NOT_SIGNED, "")
        else:
            valid_paths.append(path)

    if not valid_paths:
        return results

    try:
        # 使用换行符拼接路径，并 Base64 编码
        paths_str = "\n".join(valid_paths)
        b64_paths = base64.b64encode(paths_str.encode("utf-8")).decode("utf-8")
        
        # 组装完整的 PowerShell 脚本
        script = _PS_BATCH_SCRIPT.format(b64_paths=b64_paths)
        
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        stdout = proc.stdout.strip()
        if not stdout:
            logger.error("  [SigBatch] PowerShell 返回空结果")
            # 失败兜底
            for p in valid_paths:
                results[p] = (SigStatus.ERROR, "")
            return results

        # 针对可能单个对象或数组不同情况做兼容解析
        try:
            parsed = json.loads(stdout)
            if not isinstance(parsed, list):
                parsed = [parsed]
        except json.JSONDecodeError as e:
            logger.error(f"  [SigBatch] JSON 解析失败: {e}\n  原始输出: {stdout[:200]}...")
            for p in valid_paths:
                results[p] = (SigStatus.ERROR, "")
            return results

        # 映射回结果字典
        for item in parsed:
            p = item.get("Path", "")
            raw_status = item.get("Status", "UnknownError")
            raw_signer = item.get("Signer", "")
            
            sig_status = _STATUS_MAP.get(raw_status, SigStatus.ERROR)
            sig_signer = _extract_cn(raw_signer) if sig_status == SigStatus.VALID else ""
            
            # 使用归一化的路径作为 key 匹配以防万一
            normalized_p = os.path.normpath(p)
            for original_p in valid_paths:
                if os.path.normpath(original_p) == normalized_p:
                    results[original_p] = (sig_status, sig_signer)
                    break

        # 处理可能漏掉的文件
        for p in valid_paths:
            if p not in results:
                results[p] = (SigStatus.ERROR, "")

        return results

    except subprocess.TimeoutExpired:
        logger.warning(f"  [SigBatch] 批量核验超时（>{_TIMEOUT_SEC}s）")
        for p in valid_paths:
            results[p] = (SigStatus.ERROR, "")
        return results
    except Exception as e:
        logger.warning(f"  [SigBatch] 批量核验引发异常: {e}")
        for p in valid_paths:
            results[p] = (SigStatus.ERROR, "")
        return results


def _extract_cn(subject: str) -> str:
    """提取 CN 字段值"""
    if not subject:
        return ""
    for part in subject.split(","):
        part = part.strip()
        if part.upper().startswith("CN="):
            return part[3:].strip()
    return subject
