"""引擎/模型按需下载（带进度回调，zip 自动解压）。"""

from __future__ import annotations

import asyncio
import time
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from playgo import settings

ProgressCb = Callable[[dict], None]


def _items() -> dict[str, dict]:
    return {
        "strong-model": {
            "url": settings.URL_STRONG_MODEL,
            "kind": "file",
            "dest": settings.DOWNLOADED_DIR / settings.STRONG_MODEL_NAME,
            "label": "强网络 b18c384nbt（94MB）",
        },
        "opencl-exe": {
            "url": settings.URL_OPENCL_ZIP,
            "kind": "zip",
            "dest": settings.DOWNLOADED_DIR / "katago-opencl.zip",
            "extract_to": settings.DOWNLOADED_DIR / "opencl",
            "marker": settings.DOWNLOADED_DIR / "opencl" / "katago.exe",
            "label": "GPU 引擎 OpenCL（6MB）",
        },
        "eigen-exe": {
            "url": settings.URL_EIGEN_ZIP,
            "kind": "zip",
            "dest": settings.BUNDLED_DIR / "katago-eigen.zip",
            "extract_to": settings.BUNDLED_DIR / "eigen",
            "marker": settings.BUNDLED_DIR / "eigen" / "katago.exe",
            "label": "CPU 引擎 Eigen（6MB）",
        },
    }


def installed(id_: str) -> bool:
    item = _items()[id_]
    if item["kind"] == "zip":
        return Path(item["marker"]).exists()
    return Path(item["dest"]).exists()


def _download_one(id_: str, cb: ProgressCb | None) -> None:
    item = _items()[id_]
    dest = Path(item["dest"])
    if dest.exists() and (item["kind"] == "file" or Path(item["marker"]).exists()):
        cb and cb({"id": id_, "phase": "done", "pct": 100})
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(item["url"], headers={"User-Agent": "PlayGo/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp, tmp.open("wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if cb and total:
                    speed = got / max(time.monotonic() - t0, 0.1) / 1024
                    cb(
                        {
                            "id": id_,
                            "phase": "downloading",
                            "pct": round(got / total * 100, 1),
                            "got_mb": round(got / 1048576, 1),
                            "total_mb": round(total / 1048576, 1),
                            "speed_kbps": round(speed),
                        }
                    )
        tmp.rename(dest)
        if item["kind"] == "zip":
            cb and cb({"id": id_, "phase": "extracting", "pct": 100})
            with zipfile.ZipFile(dest) as z:
                z.extractall(item["extract_to"])
        cb and cb({"id": id_, "phase": "done", "pct": 100, "label": item["label"]})
    except Exception as e:
        tmp.unlink(missing_ok=True)
        cb and cb({"id": id_, "phase": "error", "error": str(e)})
        raise


class DownloadManager:
    def __init__(self) -> None:
        self.active_ids: set[str] = set()
        self.task: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, ids: list[str], cb: ProgressCb) -> None:
        if self.busy:
            msg = "已有下载任务进行中"
            raise RuntimeError(msg)
        valid = [i for i in ids if i in _items()]
        if not valid:
            msg = "没有可下载项"
            raise RuntimeError(msg)
        self.active_ids = set(valid)

        async def _run() -> None:
            try:
                for id_ in valid:
                    await asyncio.to_thread(_download_one, id_, cb)
            finally:
                self.active_ids.clear()

        self.task = asyncio.create_task(_run())
