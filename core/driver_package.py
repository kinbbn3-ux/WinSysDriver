# -*- coding: utf-8 -*-
"""传统 INF 驱动包的暂存、解包和目录签名校验。"""

import os
import re
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from typing import Iterator

from models.driver_info import InstallerType
from utils.pe_reader import verify_signature
from utils.logger import get_logger

logger = get_logger("DriverPackage")


@contextmanager
def stage_inf_package(
    file_path: str, installer_type: InstallerType
) -> Iterator[tuple[str, list[str]]]:
    """将 INF、CAB 或 ZIP 驱动包准备为可交给 pnputil 的 INF 列表。"""
    if installer_type == InstallerType.INF:
        yield os.path.dirname(file_path), [file_path]
        return

    with tempfile.TemporaryDirectory(prefix="driver_pkg_") as staging_dir:
        if installer_type == InstallerType.CAB:
            result = subprocess.run(
                ["expand.exe", "-F:*", file_path, staging_dir],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "CAB 驱动包解压失败")
        elif installer_type == InstallerType.ZIP:
            _extract_zip_safely(file_path, staging_dir)
        else:
            raise ValueError(f"不支持的 INF 驱动包类型: {installer_type.value}")

        inf_files = []
        for root, _, files in os.walk(staging_dir):
            inf_files.extend(
                os.path.join(root, name)
                for name in files
                if name.lower().endswith(".inf")
            )
        yield staging_dir, sorted(inf_files, key=str.lower)


def verify_driver_package(
    file_path: str, installer_type: InstallerType
) -> tuple[bool, str]:
    """验证 EXE/MSI 或传统 INF 包的 Authenticode 签名。"""
    if installer_type not in {
        InstallerType.INF,
        InstallerType.CAB,
        InstallerType.ZIP,
    }:
        return verify_signature(file_path)

    try:
        with stage_inf_package(file_path, installer_type) as (root, inf_files):
            catalogs = _find_catalog_files(root, inf_files)
            if not catalogs:
                return False, ""

            signers = []
            for catalog in catalogs:
                valid, signer = verify_signature(catalog)
                if not valid:
                    return False, ""
                if signer:
                    signers.append(signer)
            return True, signers[0] if signers else ""
    except Exception as error:
        logger.warning(f"驱动包签名校验失败 [{file_path}]: {error}")
        return False, ""


def read_inf_metadata(
    file_path: str, installer_type: InstallerType
) -> dict[str, str]:
    """读取传统驱动包中第一个 INF 的 Version 元数据。"""
    if installer_type not in {
        InstallerType.INF,
        InstallerType.CAB,
        InstallerType.ZIP,
    }:
        return {}

    try:
        with stage_inf_package(file_path, installer_type) as (_, inf_files):
            if not inf_files:
                return {}
            return _parse_inf_metadata(inf_files[0])
    except Exception as error:
        logger.debug(f"读取 INF 元数据失败 [{file_path}]: {error}")
        return {}


def _parse_inf_metadata(inf_path: str) -> dict[str, str]:
    sections: dict[str, dict[str, str]] = {}
    current_section = ""
    strings: dict[str, str] = {}

    for raw_line in _read_inf_lines(inf_path):
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip().lower()
            sections.setdefault(current_section, {})
            continue
        if "=" not in line or not current_section:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower()
        value = _clean_inf_value(value.strip())
        sections[current_section][key] = value
        if current_section == "strings":
            strings[key] = value

    version = sections.get("version", {})

    def expand(value: str) -> str:
        return re.sub(
            r"%([^%]+)%",
            lambda match: strings.get(match.group(1).strip().lower(), match.group(0)),
            value,
            flags=re.IGNORECASE,
        ).strip()

    driver_version = expand(version.get("driverver", ""))
    if "," in driver_version:
        driver_version = driver_version.split(",", 1)[1].strip()

    return {
        "provider": expand(version.get("provider", "")),
        "class": expand(version.get("class", "")),
        "class_guid": expand(version.get("classguid", "")),
        "catalog_file": expand(version.get("catalogfile", "")),
        "driver_version": driver_version,
    }


def _read_inf_lines(inf_path: str) -> list[str]:
    with open(inf_path, "rb") as stream:
        data = stream.read()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16", "utf-8-sig", "gb18030", "cp1252")
    else:
        encodings = ("utf-8-sig", "gb18030", "cp1252")
    for encoding in encodings:
        try:
            return data.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    return data.decode(errors="replace").splitlines()


def _clean_inf_value(value: str) -> str:
    in_quotes = False
    for index, character in enumerate(value):
        if character == '"':
            in_quotes = not in_quotes
        elif character == ";" and not in_quotes:
            value = value[:index]
            break
    return value.strip().strip('"')


def _extract_zip_safely(file_path: str, target_dir: str):
    target_root = os.path.realpath(target_dir)
    with zipfile.ZipFile(file_path, "r") as archive:
        for member in archive.infolist():
            member_path = os.path.realpath(
                os.path.join(target_root, member.filename)
            )
            try:
                inside_root = os.path.commonpath([target_root, member_path]) == target_root
            except ValueError:
                inside_root = False
            if not inside_root:
                raise RuntimeError(f"ZIP 路径逃逸: {member.filename}")
            archive.extract(member, target_root)


def _find_catalog_files(root: str, inf_files: list[str]) -> list[str]:
    referenced: list[str] = []
    catalog_pattern = re.compile(
        r"^\s*CatalogFile(?:\.[^=\s]+)?\s*=\s*([^;\s]+)",
        re.IGNORECASE | re.MULTILINE,
    )

    for inf_file in inf_files:
        try:
            with open(inf_file, "r", encoding="utf-8", errors="ignore") as stream:
                content = stream.read()
        except OSError:
            continue
        for name in catalog_pattern.findall(content):
            candidate = os.path.realpath(os.path.join(os.path.dirname(inf_file), name))
            if os.path.isfile(candidate):
                referenced.append(candidate)

    catalogs = referenced
    if not catalogs:
        for current_root, _, files in os.walk(root):
            catalogs.extend(
                os.path.realpath(os.path.join(current_root, name))
                for name in files
                if name.lower().endswith(".cat")
            )

    unique = {}
    for catalog in catalogs:
        unique[os.path.normcase(catalog)] = catalog
    return list(unique.values())
