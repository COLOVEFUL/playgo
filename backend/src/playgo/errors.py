"""统一错误结构：稳定 code + params，前端据此显示本地化文案。

协议约定：所有面向用户的错误（REST detail / WS 事件）只携带
``{"code": <稳定码>, "args": <插值参数>}``；中文 message 仅供日志。
"""

from __future__ import annotations


class PlayGoError(Exception):
    """领域异常基类。

    code 供前端查词典（如 ``move.occupied``）；params 为文案插值参数
    （属性名不得用 args —— 与 BaseException.args 冲突）。
    """

    code = "error.unknown"

    def __init__(
        self, msg: str = "", *, code: str | None = None, params: dict | None = None
    ) -> None:
        super().__init__(msg)
        if code:
            self.code = code
        self.params = params or {}


def err_detail(code: str, params: dict | None = None) -> dict:
    """HTTPException 的 detail 载荷（稳定码 + 插值参数）。"""
    return {"code": code, "args": params or {}}


def payload_of(e: Exception) -> dict:
    """从任意异常提取错误载荷；无码异常给 unknown 兜底。"""
    if isinstance(e, PlayGoError):
        return err_detail(e.code, e.params)
    return err_detail("error.unknown", {"detail": str(e)})


class DownloadError(PlayGoError):
    """下载任务错误。"""
