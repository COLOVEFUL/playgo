"""SGF 棋谱读写（FF[4]，中国规则）。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from playgo.errors import RecordError
from playgo.rules import BLACK, WHITE, Board, IllegalMove

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
    if len(s) != 2 or any(c not in _SGF_COL[:size] for c in s):
        msg = "SGF坐标越界"
        raise ValueError(msg)
    x, y = _SGF_COL.index(s[0]), _SGF_COL.index(s[1])
    return y * size + x


@dataclass
class SgfGame:
    size: int = 19
    komi: float = 7.5
    rule: str = "Chinese"
    black_name: str = "Black"
    white_name: str = "White"
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


class _SgfReader:
    """顺序解析属性与树结构；评论中的括号/伪着法不参与结构解析。"""

    def __init__(self, text: str) -> None:
        self.text = text.lstrip("\ufeff")
        self.pos = 0
        self.charset_span: tuple[int, int] | None = None

    def peek(self) -> str:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1
        return self.text[self.pos : self.pos + 1]

    def value(self) -> str:
        self.pos += 1  # [
        out = []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == "]":
                return "".join(out)
            if char == "\\":
                if self.pos >= len(self.text):
                    break
                char = self.text[self.pos]
                self.pos += 1
                if char in "\r\n":
                    if char == "\r" and self.text[self.pos : self.pos + 1] == "\n":
                        self.pos += 1
                    continue
            out.append(char)
        msg = "SGF属性未闭合"
        raise ValueError(msg)

    def node(self) -> dict[str, list[str]]:
        props: dict[str, list[str]] = {}
        while self.peek() and self.peek() not in ";()":
            start = self.pos
            while self.pos < len(self.text) and "A" <= self.text[self.pos] <= "Z":
                self.pos += 1
            key = self.text[start : self.pos]
            if not key or key in props or self.peek() != "[":
                msg = "SGF属性格式错误"
                raise ValueError(msg)
            values = []
            while self.peek() == "[":
                start = self.pos
                values.append(self.value())
                if key == "CA" and self.charset_span is None:
                    self.charset_span = (start, self.pos)
            props[key] = values
        return props

    def mainline(self) -> list[dict[str, list[str]]]:
        stack: list[dict] = []
        nodes = []
        roots = 0
        while char := self.peek():
            self.pos += 1
            if char == "(":
                if stack and not stack[-1]["nodes"]:
                    msg = "SGF分支缺少根节点"
                    raise ValueError(msg)
                selected = (
                    roots == 0
                    if not stack
                    else stack[-1]["selected"] and not stack[-1]["children"]
                )
                if stack:
                    stack[-1]["children"] += 1
                else:
                    roots += 1
                stack.append({"selected": selected, "nodes": 0, "children": 0})
            elif char == ";" and stack and not stack[-1]["children"]:
                node = self.node()
                stack[-1]["nodes"] += 1
                if stack[-1]["selected"]:
                    nodes.append(node)
            elif char == ")" and stack and stack[-1]["nodes"]:
                stack.pop()
            else:
                msg = "SGF树结构错误"
                raise ValueError(msg)
        if stack or not nodes:
            msg = "SGF棋谱不完整"
            raise ValueError(msg)
        return nodes


def parse_sgf(text: str) -> SgfGame:
    """解析第一盘棋的第一主变；不把旁支或评论误当连续着法。"""
    nodes = _SgfReader(text).mainline()
    return _game_from_nodes(nodes)


def _game_from_nodes(nodes: list[dict[str, list[str]]]) -> SgfGame:
    root = nodes[0]
    g = SgfGame(
        size=int(root.get("SZ", ["19"])[0]),
        komi=float(root.get("KM", ["7.5"])[0]),
        rule=root.get("RU", ["Chinese"])[0],
        black_name=root.get("PB", ["Black"])[0],
        white_name=root.get("PW", ["White"])[0],
        date=root.get("DT", [""])[0],
        result=root.get("RE", [""])[0],
    )
    if not 2 <= g.size <= 19 or not math.isfinite(g.komi):
        msg = "SGF棋盘尺寸或贴目不支持"
        raise ValueError(msg)
    for props in nodes:
        if "B" in props and "W" in props:
            msg = "SGF同节点包含双方着法"
            raise ValueError(msg)
        for tag, color in (("B", BLACK), ("W", WHITE)):
            if tag in props:
                if len(props[tag]) != 1:
                    msg = "SGF同节点包含多手着法"
                    raise ValueError(msg)
                g.moves.append((color, from_sgf_coords(props[tag][0], g.size)))
    return g


def validate_import(raw: bytes) -> tuple[SgfGame, str]:
    """解码、校验主变并保留原文，禁止导入后静默丢失摆子局面。"""
    # Latin-1 一一对应原字节，先安全读取根属性中的编码声明。
    root = _SgfReader(raw.decode("latin-1").removeprefix("ï»¿")).mainline()[0]
    if "CA" in root and (len(root["CA"]) != 1 or not root["CA"][0]):
        msg = "SGF编码声明无效"
        raise ValueError(msg)
    charset = root.get("CA", [""])[0]
    if charset:
        text = raw.decode(charset).lstrip("\ufeff")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")
    reader = _SgfReader(text)
    nodes = reader.mainline()
    if nodes[0].get("GM", ["1"]) != ["1"]:
        raise RecordError(code="record.unsupported_sgf")
    if int(nodes[0].get("HA", ["0"])[0]) or any(
        set(node) & {"AB", "AW", "AE", "PL"} for node in nodes
    ):
        raise RecordError(code="record.unsupported_sgf")
    game = _game_from_nodes(nodes)
    board = Board(game.size, game.komi)
    try:
        for color, point in game.moves:
            board.play(color, point)
    except IllegalMove as exc:
        raise RecordError from exc
    # 棋谱库统一UTF-8，保留评论/分支，只改真实编码属性（不能替换评论里的CA文本）。
    if charset and reader.charset_span:
        start, end = reader.charset_span
        text = text[:start] + "[UTF-8]" + text[end:]
    else:
        start = text.index(";") + 1
        text = text[:start] + "CA[UTF-8]" + text[start:]
    return game, text


def save_record(g: SgfGame, records_dir: Path) -> Path:
    """保存到 records/YYYY-MM-DD/NNN-结果.sgf，返回路径。结果用 SGF 标准码（语言中立）。"""
    day_dir = records_dir / (g.date or datetime.now().strftime("%Y-%m-%d"))
    day_dir.mkdir(parents=True, exist_ok=True)
    seq = len(list(day_dir.glob("*.sgf"))) + 1
    tag = (g.result or "?").replace(",", "-")
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
