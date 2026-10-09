# -*- coding: utf-8 -*-
"""
装机方案管理器

将用户配置好的安装列表（包括文件路径、用户传参、勾选状态等）
持久化为 JSON 文件，并在下次使用时加载分析。
"""

import json
import os
from datetime import datetime
from typing import Dict, Any

from models.package_info import PackageInfo

_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))


def save_preset(name: str, folder_path: str, packages: list[PackageInfo]) -> str:
    """
    保存装机方案到 JSON 文件。
    返回保存的文件绝对路径。
    """
    os.makedirs(_DATA_DIR, exist_ok=True)
    # 处理文件名的非法字符
    safe_name = "".join(c if c.isalnum() else "_" for c in name)
    file_name = f"preset_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    file_path = os.path.join(_DATA_DIR, file_name)

    data = {
        "version": 1,
        "name": name,
        "created_at": datetime.now().isoformat(),
        "folder": folder_path,
        "packages": []
    }

    for pkg in packages:
        # 只保存重要字段，UI在恢复时基于文件路径反向覆盖
        p_data = {
            "file_path": pkg.file_path,
            "enabled": pkg.enabled,
            "user_override_args": pkg.user_override_args,
            "add_to_path": pkg.add_to_path,
            "create_shortcut": pkg.create_shortcut,
        }
        data["packages"].append(p_data)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return file_path


def load_preset(file_path: str) -> Dict[str, Any]:
    """
    加载装机方案 JSON。
    由于返回的内容需要重新与扫描的 PackageInfo 结合（重新生成实例），
    这里仅返回解析出的字典数据，由上层负责恢复状态。
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)
