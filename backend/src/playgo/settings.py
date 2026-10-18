"""全局配置：路径、用时规则、AI 难度档位（棋力对照）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
PROJECT_DIR = BASE_DIR.parent  # 仓库根
ENGINES_DIR = BASE_DIR / "engines"
BUNDLED_DIR = ENGINES_DIR / "bundled"
DOWNLOADED_DIR = ENGINES_DIR / "downloaded"
RECORDS_DIR = PROJECT_DIR / "records"
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"
LOGS_DIR = ENGINES_DIR / "logs"

for _d in (ENGINES_DIR, BUNDLED_DIR, DOWNLOADED_DIR, RECORDS_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

HOST = "127.0.0.1"
PORT = 8900

BOARD_SIZE = 19
KOMI = 7.5

# KataGo 官方发布与模型直链
URL_EIGEN_ZIP = (
    "https://github.com/lightvector/KataGo/releases/download/"
    "v1.18.1/katago-v1.18.1-eigen-windows-x64.zip"
)
URL_OPENCL_ZIP = (
    "https://github.com/lightvector/KataGo/releases/download/"
    "v1.18.1/katago-v1.18.1-opencl-windows-x64.zip"
)
URL_STRONG_MODEL = (
    "https://media.katagotraining.org/uploaded/networks/models/kata1/"
    "kata1-b18c384nbt-s9996604416-d4316597426.bin.gz"
)
STRONG_MODEL_NAME = "kata1-b18c384nbt.bin.gz"
HUMAN_MODEL_NAME = "b18c384nbt-humanv0.bin.gz"
URL_HUMAN_MODEL = (
    "https://github.com/lightvector/KataGo/releases/download/v1.15.0/b18c384nbt-humanv0.bin.gz"
)

# CPU 轻量网络：官方 Extra Networks 的 lionffen b6c64（约 2MB，19x19 专用，
# 强度约等于历史 10 层网络）。保留 .txt.gz 真实扩展名——官方即旧格式。
URL_LITE_MODEL = (
    "https://media.katagotraining.org/uploaded/networks/models_extra/lionffen_b6c64_3x3_v10.txt.gz"
)
LITE_MODEL_NAME = "lionffen_b6c64.txt.gz"


@dataclass(frozen=True)
class EnginePackage:
    """一个可选择的引擎包：后端 exe + 配套网络 + 所需下载项 id。"""

    id: str  # "cpu" | "gpu"
    backend: str  # "eigen" | "opencl"
    exe: Path
    model: Path
    items: tuple[str, ...]  # downloader._items() 的 id


# 引擎分包：CPU 包默认（Eigen + 轻量网络，下载约 8MB，无显卡也流畅）；
# GPU 包按需（OpenCL + 强网络，下载约 100MB，需独立显卡）。
PACKAGES: dict[str, EnginePackage] = {
    "cpu": EnginePackage(
        "cpu",
        "eigen",
        BUNDLED_DIR / "eigen" / "katago.exe",
        DOWNLOADED_DIR / LITE_MODEL_NAME,
        ("eigen-exe", "lite-model"),
    ),
    "gpu": EnginePackage(
        "gpu",
        "opencl",
        DOWNLOADED_DIR / "opencl" / "katago.exe",
        DOWNLOADED_DIR / STRONG_MODEL_NAME,
        ("opencl-exe", "strong-model"),
    ),
}


@dataclass(frozen=True)
class TimeSettings:
    """主时 + 读秒。默认：主时 30:00，读秒 60s ×3，用尽判负。"""

    main_seconds: int = 1800
    byo_seconds: int = 60
    byo_periods: int = 3

    @staticmethod
    def presets() -> dict[str, TimeSettings]:
        return {
            "standard": TimeSettings(),  # 30:00 + 60s×3
            "blitz": TimeSettings(300, 30, 3),  # 5:00 + 30s×3
            "long": TimeSettings(3600, 60, 5),  # 60:00 + 60s×5
            "free": TimeSettings(0, 0, 0),  # 不计时
        }


# ── AI 段级位（Human SL / KaTrain 快速估计，均未经本项目实战校准） ─────────────
# rank_* 是人类棋风目标，非中国考段认证；高段原始策略可能达不到目标棋力。
# 64 visits 仅让主网络判断何时停一手；落点始终按完整 humanPolicy 原概率采样，
# 不截取搜索候选、不改变温度、不混入主网络最优点，避免无依据改变等级。
DEFAULT_DIFFICULTY = "10k"
DIFFICULTY_PRESETS: dict[str, dict] = {
    rank: {"pick": "human", "profile": f"rank_{rank}", "visits": 64, "cpu_visits": 64}
    for rank in ("20k", "15k", "10k", "5k", "1k", "1d", "3d", "5d", "7d", "9d")
}
DIFFICULTY_PRESETS["max"] = {"pick": "best", "visits": 800, "cpu_visits": 160}
QUICK_RANKS = {"15k": 15, "10k": 10, "5k": 5, "1k": 1, "1d": 0, "3d": -2}
# 兼容旧 API 调用；旧档位没有可靠等级，统一迁移到明确的新策略。
DIFFICULTY_ALIASES = {"easy": "15k", "medium": "1d", "hard": "max"}


def normalize_difficulty(value: str) -> str:
    return DIFFICULTY_ALIASES.get(value, value)


# AI 推荐 / 形势判断所用计算量（始终用当前可用最强引擎）
HINT_VISITS = 200
HINT_VISITS_CPU = 80
# 引擎配置的硬上限统一管理；推荐不修改模型，也不无限追加搜索。
ENGINE_MAX_VISITS = 100_000
HINT_DEEP_VISITS = 8_000
HINT_DEEP_VISITS_CPU = 1_600
HINT_QUICK_SECONDS = 2.0
HINT_DEEP_SECONDS = 25.0
HINT_TOTAL_SECONDS = 30.0  # 包含排队/启动等待；到时保留最新可用推荐
HINT_REPORT_SECONDS = 0.25
TERRITORY_VISITS = 120
TERRITORY_VISITS_CPU = 60
REVIEW_VISITS = 64  # 复盘批量分析每手的 visits（速度与质量折中）
