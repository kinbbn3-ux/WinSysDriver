# -*- coding: utf-8 -*-
"""
核心抽象接口定义

为驱动安装、软件安装及未来局域网推送提供统一协议。
"""

from abc import ABC, abstractmethod
from typing import Optional


class IInstallBackend(ABC):
    """
    安装后端统一接口

    所有安装执行器（驱动/软件/网络推送）都应实现此接口，
    确保 TaskDispatcher 可以透明地调度不同类型的安装任务。
    """

    @abstractmethod
    def execute(self, item) -> tuple[bool, str, Optional[int]]:
        """
        执行单个安装任务

        Args:
            item: 安装项（DriverInfo 或 PackageInfo）

        Returns:
            (是否成功, 消息, 返回码) 元组
        """
        ...

    @abstractmethod
    def cancel(self) -> None:
        """取消当前安装任务"""
        ...


class ITaskDispatcher(ABC):
    """
    任务分发接口

    当前为本地单机模式，预留未来扩展为局域网分发的接口。
    实现类负责维护任务队列、调度顺序和进度汇报。
    """

    @abstractmethod
    def dispatch(self, tasks: list, backend: IInstallBackend) -> None:
        """
        开始分发并执行任务队列

        Args:
            tasks: 安装任务列表
            backend: 安装后端实现
        """
        ...

    @abstractmethod
    def get_status(self) -> dict:
        """获取当前分发状态摘要"""
        ...
