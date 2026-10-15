"""围棋规则引擎 —— 中国规则（数子法），支持位置超级劫。

纯逻辑、无副作用，供对局状态机与测试直接调用。
坐标系：point = y * size + x，左上为原点，x 向右、y 向下。
"""

from __future__ import annotations

from dataclasses import dataclass, field

EMPTY = 0
BLACK = 1
WHITE = 2

PASS: int | None = None  # 停一手


def opponent(color: int) -> int:
    return BLACK + WHITE - color


class IllegalMove(Exception):
    """非法落子（占位/自杀/打劫等）。"""


@dataclass(frozen=True)
class ScoreResult:
    black_area: float
    white_area: float  # 已含贴目
    winner: int  # BLACK / WHITE；相等(和棋)时为 0
    margin: float  # 胜多少目
    ownership: list[int]  # 每点归属：1 黑 / 2 白 / 0 中立公气，供 UI 热力图


@dataclass
class PlayResult:
    color: int
    point: int | None
    captured: list[int] = field(default_factory=list)  # 被提走的子（用于动画）


class Board:
    """一局棋的棋盘状态（含历史，用于超级劫判定）。"""

    def __init__(self, size: int = 19, komi: float = 7.5, superko: bool = True) -> None:
        if size < 2 or size > 25:
            msg = f"不支持的棋盘尺寸: {size}"
            raise ValueError(msg)
        self.size = size
        self.komi = komi
        self.superko = superko
        self.grid: bytearray = bytearray(size * size)
        self.captures = {BLACK: 0, WHITE: 0}  # 各方提走的对方子数
        # 位置超级劫：出现过 (棋盘快照, 下一手行棋方) 的集合
        self._pos_keys: set[tuple[bytes, int]] = {(bytes(self.grid), BLACK)}
        self.last_point: int | None = None
        self.consecutive_passes = 0
        self.move_count = 0

    # ── 基础查询 ──────────────────────────────────────────

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size

    def neighbors(self, point: int) -> list[int]:
        x, y = point % self.size, point // self.size
        out = []
        if x > 0:
            out.append(point - 1)
        if x < self.size - 1:
            out.append(point + 1)
        if y > 0:
            out.append(point - self.size)
        if y < self.size - 1:
            out.append(point + self.size)
        return out

    def color_at(self, point: int) -> int:
        return self.grid[point]

    def group_and_liberties(self, point: int) -> tuple[set[int], set[int]]:
        """返回 (棋连整体, 气集合)。"""
        color = self.grid[point]
        if color == EMPTY:
            return set(), set()
        stones, libs, stack = {point}, set(), [point]
        while stack:
            p = stack.pop()
            for n in self.neighbors(p):
                c = self.grid[n]
                if c == EMPTY:
                    libs.add(n)
                elif c == color and n not in stones:
                    stones.add(n)
                    stack.append(n)
        return stones, libs

    def legal(self, color: int, point: int) -> bool:
        try:
            self._try_play(color, point)
        except IllegalMove:
            return False
        return True

    def legal_moves(self, color: int) -> list[int]:
        return [p for p in range(self.size * self.size) if self.legal(color, p)]

    # ── 行棋 ─────────────────────────────────────────────

    def play(self, color: int, point: int | None) -> PlayResult:
        """落子或停一手。非法时抛 IllegalMove。"""
        if point is PASS:
            self.consecutive_passes += 1
            self.last_point = None
            self.move_count += 1
            return PlayResult(color, None)

        if not 0 <= point < self.size * self.size:
            msg = f"落点越界: {point}"
            raise IllegalMove(msg)
        if self.grid[point] != EMPTY:
            msg = f"该点已有棋子: {point}"
            raise IllegalMove(msg)

        snapshot = bytes(self.grid)
        captured = self._try_play(color, point, snapshot)

        self.last_point = point
        self.consecutive_passes = 0
        self.move_count += 1
        return PlayResult(color, point, captured)

    def _try_play(self, color: int, point: int, snapshot: bytes | None = None) -> list[int]:
        """试下一手：成功则落定并返回提子列表；失败抛异常且不改变状态。"""
        if point is PASS:
            return []
        if not 0 <= point < self.size * self.size or self.grid[point] != EMPTY:
            msg = "非法落点"
            raise IllegalMove(msg)
        if snapshot is None:
            snapshot = bytes(self.grid)

        self.grid[point] = color
        captured: list[int] = []
        opp = opponent(color)
        checked: set[int] = set()
        for n in self.neighbors(point):
            if self.grid[n] == opp and n not in checked:
                stones, libs = self.group_and_liberties(n)
                checked |= stones
                if not libs:
                    for s in stones:
                        self.grid[s] = EMPTY
                    captured.extend(sorted(stones))

        _, my_libs = self.group_and_liberties(point)
        if not my_libs:
            self.grid = bytearray(snapshot)  # 自杀，还原
            msg = "禁着点：自杀"
            raise IllegalMove(msg)

        key = (bytes(self.grid), opponent(color))
        if self.superko and key in self._pos_keys:
            self.grid = bytearray(snapshot)  # 打劫（重现历史局面），还原
            msg = "打劫：不可立即重现先前局面"
            raise IllegalMove(msg)

        self.captures[color] += len(captured)
        self._pos_keys.add(key)
        return captured

    # ── 终局点目（中国规则数子法） ────────────────────────

    def is_over_by_passes(self) -> bool:
        return self.consecutive_passes >= 2

    def _flood_empty_region(
        self, start: int, visited: list[bool], dead: set[int]
    ) -> tuple[list[int], set[int]]:
        """从空点 start 泛洪，返回 (区域点集, 相邻棋色集合)。"""
        region, borders, stack = [], set(), [start]
        visited[start] = True
        while stack:
            q = stack.pop()
            region.append(q)
            for nb in self.neighbors(q):
                c = self.grid[nb]
                if c == EMPTY:
                    if not visited[nb]:
                        visited[nb] = True
                        stack.append(nb)
                elif nb in dead:
                    borders.add(opponent(c))
                else:
                    borders.add(c)
        return region, borders

    def score(self, dead_stones: set[int] | None = None) -> ScoreResult:
        """数子法：子 + 围空。dead_stones 中的死子点判给对方。

        dead_stones 由引擎 ownership 或玩家手动标记给出。
        """
        dead = dead_stones or set()
        n2 = self.size * self.size
        owner = [0] * n2

        # 1. 活子归属；死子视为对方点
        for p in range(n2):
            c = self.grid[p]
            if c != EMPTY:
                owner[p] = opponent(c) if p in dead else c

        # 2. 空点区域：仅接触单一颜色则归该色，否则中立
        visited = [False] * n2
        for p in range(n2):
            if self.grid[p] == EMPTY and not visited[p]:
                region, borders = self._flood_empty_region(p, visited, dead)
                if len(borders) == 1:
                    b = borders.pop()
                    for q in region:
                        owner[q] = b

        black = sum(1 for o in owner if o == BLACK)
        white = sum(1 for o in owner if o == WHITE) + self.komi
        if black > white:
            winner, margin = BLACK, black - white
        elif white > black:
            winner, margin = WHITE, white - black
        else:
            winner, margin = 0, 0.0
        return ScoreResult(black, white, winner, margin, owner)
