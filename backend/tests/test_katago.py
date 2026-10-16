"""KataGo 封装的纯逻辑测试（不启动真实引擎）。"""

from pathlib import Path

from playgo.katago import KataGoEngine, from_kata_coords, to_kata_coords


def test_coord_roundtrip():
    assert to_kata_coords(3 + 3 * 19) == "D16"
    assert to_kata_coords(15 + 2 * 19) == "Q17"
    assert from_kata_coords("D16") == 3 + 3 * 19
    assert from_kata_coords("Q17") == 15 + 2 * 19


def test_auto_timeout_scales_with_visits_and_backend():
    gpu = KataGoEngine(Path("x"), Path("y"), "opencl")
    cpu = KataGoEngine(Path("x"), Path("y"), "eigen")
    assert gpu.auto_timeout(200) == 60.0  # 触及下限
    assert gpu.auto_timeout(800) == 126.0  # 30 + 800*0.12（困难档 GPU）
    assert cpu.auto_timeout(160) == 430.0  # 30 + 160*2.5（困难档 CPU 回退）
