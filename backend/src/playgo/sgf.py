"""SGF 棋谱读写（FF[4]，中国规则）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from playgo.rules import BLACK, WHITE

if TYPE_CHECKING:
    from pathlib import Path

_SGF_COL = "abcdefghijklmnopqrs"  # 19 路（SGF 坐标不跳 I，a-s 连续）


def to_sgf_coords(point: int | None, size: int = 19) -> str:
    """内部坐标 → SGF。pass 为空串。SGF 的 y 从顶部数。"""
    if point is None:
        return ""
    x, y = point % size, point // size
    return _SGF_COL[x] + _SGF_COL[y]


def from_sgf_coords(s: str, size: int = 19) -> int | None:
    if not s or s == "tt":
        return None
    x, y = _SGF_COL.index(s[0]), _SGF_COL.index(s[1])
    return y * size + x


@dataclass
class SgfGame:
    size: int = 19
    komi: float = 7.5
    rule: str = "Chinese"
    black_name: str = "黑方"
    white_name: str = "白方"
    date: str = ""
    result: str = ""
    main_time: int = 1800
    byo_seconds: int = 60
    byo_periods: int = 3
    moves: list[tuple[int, int | None]] = field(default_factory=list)  # (color, point)
    time_left: list[float] = field(default_factory=list)  # 每手后剩余秒

    def to_sgf(self) -> str:
        props = [
            f"GM[1]FF[4]CA[UTF-8]SZ[{self.size}]",
            f"KM[{self.komi}]RU[{self.rule}]",
            f"PB[{_esc(self.black_name)}]PW[{_esc(self.white_name)}]",
            f"DT[{self.date or datetime.now().strftime('%Y-%m-%d')}]",
            f"TM[{self.main_time}]OT[{self.byo_seconds}x{self.byo_periods}]",
            f"RE[{self.result or '?'}]",
            "CP[PlayGo]",
        ]
        nodes = []
        for i, (color, point) in enumerate(self.moves):
            tag = "B" if color == BLACK else "W"
            node = f";{tag}[{to_sgf_coords(point, self.size)}]"
            if i < len(self.time_left):
                t = self.time_left[i]
                if t >= 0:
                    node += f"BL[{t:.0f}]" if color == BLACK else f"WL[{t:.0f}]"
            nodes.append(node)
        return "(;" + "".join(props) + "".join(nodes) + ")"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("]", "\\]")


_PROP_RE = re.compile(r"([A-Z]{1,2})\[((?:\\\]|[^])])*)\]")
_MOVE_RE = re.compile(r";\s*([BW])\[([a-s]{0,2})\]")


def parse_sgf(text: str) -> SgfGame:
    """解析主变（不展开分支）。"""
    g = SgfGame()
    for key, val in _PROP_RE.findall(text[: text.find(";B[") if ";B[" in text else 2000]):
        match key:
            case "SZ":
                g.size = int(val)
            case "KM":
                g.komi = float(val)
            case "RU":
                g.rule = val
            case "PB":
                g.black_name = val
            case "PW":
                g.white_name = val
            case "DT":
                g.date = val
            case "RE":
                g.result = val
    for color, coords in _MOVE_RE.findall(text):
        g.moves.append((BLACK if color == "B" else WHITE, from_sgf_coords(coords, g.size)))
    return g


def save_record(g: SgfGame, records_dir: Path) -> Path:
    """保存到 records/YYYY-MM-DD/NN-结果.sgf，返回路径。"""
    day_dir = records_dir / (g.date or datetime.now().strftime("%Y-%m-%d"))
    day_dir.mkdir(parents=True, exist_ok=True)
    seq = len(list(day_dir.glob("*.sgf"))) + 1
    tag = (g.result or "?").replace("+", "胜").replace(",", "-")
    path = day_dir / f"{seq:03d}-{tag}.sgf"
    n = 1
    while path.exists():
        n += 1
        path = day_dir / f"{seq:03d}-{tag}-{n}.sgf"
    path.write_text(g.to_sgf(), encoding="utf-8")
    return path


def list_records(records_dir: Path) -> list[dict]:
    """棋谱库列表（新在前）。"""
    out = []
    for f in sorted(records_dir.rglob("*.sgf"), reverse=True):
        try:
            g = parse_sgf(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 损坏谱跳过
            continue
        out.append(
            {
                "file": str(f.relative_to(records_dir)),
                "date": g.date,
                "black": g.black_name,
                "white": g.white_name,
                "result": g.result,
                "moves": len(g.moves),
                "komi": g.komi,
            }
        )
    return out


def result_string(winner: int | None, reason: str, margin: float = 0.0) -> str:
    """内部结果 → SGF RE 字段。"""
    if not winner:
        return "0"  # 和棋（数子完全相等时）
    who = "B" if winner == BLACK else "W"
    match reason:
        case "resign":
            return f"{who}+R"
        case "timeout":
            return f"{who}+T"
        case "score":
            m = f"{margin:g}"
            return f"{who}+{m}"
        case _:
            return f"{who}+?"
