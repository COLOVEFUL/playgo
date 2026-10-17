"""引擎分包逻辑测试（纯逻辑，不启动真实引擎；目录用 tmp_path 重定向）。

覆盖：下载目录与包注册表一致性、choice.json 读写、缺省选择推导、
候选排序（选择优先+另一包兜底）、状态视图形状。
"""

from pathlib import Path

import pytest

from playgo import downloader, katago, settings
from playgo.katago import EngineManager
from playgo.settings import EnginePackage


@pytest.fixture
def fake_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """把引擎相关目录重定向到 tmp_path 并重建包注册表。"""
    bundled = tmp_path / "bundled"
    downloaded = tmp_path / "downloaded"
    bundled.mkdir()
    downloaded.mkdir()
    monkeypatch.setattr(settings, "ENGINES_DIR", tmp_path)
    monkeypatch.setattr(settings, "BUNDLED_DIR", bundled)
    monkeypatch.setattr(settings, "DOWNLOADED_DIR", downloaded)
    monkeypatch.setattr(
        settings,
        "PACKAGES",
        {
            "cpu": EnginePackage(
                "cpu", "eigen",
                bundled / "eigen" / "katago.exe",
                downloaded / settings.LITE_MODEL_NAME,
                ("eigen-exe", "lite-model"),
            ),
            "gpu": EnginePackage(
                "gpu", "opencl",
                downloaded / "opencl" / "katago.exe",
                downloaded / settings.STRONG_MODEL_NAME,
                ("opencl-exe", "strong-model"),
            ),
        },
    )
    return {"bundled": bundled, "downloaded": downloaded}


def _install_cpu(d: dict[str, Path]) -> None:
    (d["bundled"] / "eigen").mkdir(parents=True, exist_ok=True)
    (d["bundled"] / "eigen" / "katago.exe").write_bytes(b"x")
    (d["downloaded"] / settings.LITE_MODEL_NAME).write_bytes(b"x")


def _install_gpu(d: dict[str, Path]) -> None:
    (d["downloaded"] / "opencl").mkdir(parents=True, exist_ok=True)
    (d["downloaded"] / "opencl" / "katago.exe").write_bytes(b"x")
    (d["downloaded"] / settings.STRONG_MODEL_NAME).write_bytes(b"x")


# ── 目录一致性 ──────────────────────────────────────────────


def test_catalog_consistency():
    items = downloader._items()
    for pkg in settings.PACKAGES.values():
        for i in pkg.items:
            assert i in items, f"{pkg.id} 的下载项 {i} 不在目录中"
            assert items[i]["url"]
            assert items[i]["dest"]
            assert items[i]["size_mb"] > 0
    assert set(downloader.item_ids()) == set(items)


def test_lite_model_item_installed(fake_dirs):
    assert not downloader.installed("lite-model")
    (fake_dirs["downloaded"] / settings.LITE_MODEL_NAME).write_bytes(b"x")
    assert downloader.installed("lite-model")


# ── choice.json 读写 ────────────────────────────────────────


def test_read_choice_default_when_absent_or_broken(fake_dirs):
    assert katago.read_choice() is None
    (settings.ENGINES_DIR / "choice.json").write_text("{broken", encoding="utf-8")
    assert katago.read_choice() is None
    (settings.ENGINES_DIR / "choice.json").write_text('{"engine": "tpu"}', encoding="utf-8")
    assert katago.read_choice() is None  # 非法值视为未选择


def test_write_read_roundtrip(fake_dirs):
    katago.write_choice("cpu")
    assert katago.read_choice() == "cpu"
    katago.write_choice("gpu")
    assert katago.read_choice() == "gpu"


# ── 缺省选择推导：GPU 装全→gpu（老环境），否则 cpu（全新装机）──


def test_default_choice(fake_dirs):
    assert katago._default_choice() == "cpu"
    _install_cpu(fake_dirs)
    assert katago._default_choice() == "cpu"
    _install_gpu(fake_dirs)
    assert katago._default_choice() == "gpu"


# ── 候选排序：选择优先，另一包仅在装全时兜底 ──────────────────


def test_ordered_packages_prefers_selection(fake_dirs):
    _install_cpu(fake_dirs)
    _install_gpu(fake_dirs)
    mgr = EngineManager()
    mgr.selected_id = "cpu"
    assert [p.id for p in mgr._ordered_packages()] == ["cpu", "gpu"]
    mgr.selected_id = "gpu"
    assert [p.id for p in mgr._ordered_packages()] == ["gpu", "cpu"]


def test_ordered_packages_fallback_only_if_installed(fake_dirs):
    _install_cpu(fake_dirs)  # 仅 CPU 装全
    mgr = EngineManager()
    mgr.selected_id = "gpu"  # 选中 GPU 但未装 → 只有 CPU 兜底
    assert [p.id for p in mgr._ordered_packages()] == ["gpu", "cpu"]
    mgr.selected_id = "cpu"
    assert [p.id for p in mgr._ordered_packages()] == ["cpu"]


# ── 状态视图 ────────────────────────────────────────────────


def test_package_view_fields(fake_dirs):
    _install_cpu(fake_dirs)
    mgr = EngineManager()
    mgr.selected_id = "cpu"
    mgr.engine = katago.KataGoEngine(Path("e"), Path("m"), "eigen")  # 假装在跑 CPU 包
    view = {p["id"]: p for p in (mgr._package_view(pkg) for pkg in settings.PACKAGES.values())}
    cpu, gpu = view["cpu"], view["gpu"]
    assert cpu["installed"]
    assert cpu["active"]
    assert cpu["missing"] == []
    assert cpu["size_mb"] == 0
    assert not gpu["installed"]
    assert not gpu["active"]
    assert gpu["backend"] == "opencl"
    assert gpu["gpu"] is True
    missing_ids = [m["id"] for m in gpu["missing"]]
    assert missing_ids == ["opencl-exe", "strong-model"]
    assert gpu["size_mb"] == sum(m["size_mb"] for m in gpu["missing"]) > 0


def test_status_shape(fake_dirs):
    mgr = EngineManager()
    st = mgr.status()
    assert st["selected"] == "cpu"
    assert st["engine"] is None
    assert st["available"] is False
    assert [p["id"] for p in st["packages"]] == ["cpu", "gpu"]
    assert "missing" not in st  # 顶层 missing 已由 packages[] 取代
