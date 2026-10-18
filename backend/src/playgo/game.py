"""对局状态机：行棋轮转、计时读秒、悔棋、终局流程。

服务端权威 —— 前端只发送意图（落子/停一手/认输/悔棋/死活标记），
状态与计时由本模块管理与广播。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from playgo import settings
from playgo.rules import BLACK, WHITE, Board, IllegalMove, opponent
from playgo.sgf import SgfGame, result_string

MODE_PVP = "pvp"
MODE_AI = "ai"

STATUS_PLAYING = "playing"
STATUS_SCORING = "scoring"
STATUS_ENDED = "ended"


@dataclass
class GameConfig:
    mode: str = MODE_PVP  # pvp | ai
    difficulty: str = settings.DEFAULT_DIFFICULTY  # ai 模式
    ai_style: str = "rank"  # rank=快速估计，human=官方人类棋风
    human_color: int = BLACK  # ai 模式下人类执子
    komi: float = settings.KOMI
    size: int = settings.BOARD_SIZE  # 常规对局恒 19；复盘接管可来自小棋盘棋谱
    time: settings.TimeSettings = field(default_factory=settings.TimeSettings)
    black_name: str = "Black"
    white_name: str = "White"
    takeover: bool = False  # 复盘接管试下：黑白皆由玩家执，终局不存谱
    review_source: tuple[str, int] | None = None  # 原棋谱与接管手数，供前端返回复盘

    def ai_color(self) -> int | None:
        return opponent(self.human_color) if self.mode == MODE_AI else None


@dataclass
class MoveRecord:
    n: int
    color: int
    point: int | None  # None = 停一手
    captured: list[int]
    clock_left: float  # 落子后该方剩余时间（秒；-1 不计时）


class PlayerClock:
    __slots__ = ("byo_left", "in_byo", "main", "periods_left", "unlimited")

    def __init__(self, ts: settings.TimeSettings) -> None:
        self.unlimited = ts.main_seconds <= 0
        self.main = float(ts.main_seconds)
        self.periods_left = ts.byo_periods
        self.byo_left = float(ts.byo_seconds)  # 当前读秒周期剩余；每次轮到重新满额
        self.in_byo = False

    def snapshot(self) -> dict:
        return {
            "main": self.main,
            "byo_periods": self.periods_left,
            "byo_left": self.byo_left,
            "in_byo": self.in_byo,
            "unlimited": self.unlimited,
        }


class GameSession:
    def __init__(self, cfg: GameConfig) -> None:
        self.id = uuid4().hex  # 同一秒内反复接管也必须视为新对局
        self.cfg = cfg
        self.board = Board(size=cfg.size, komi=cfg.komi)
        self.moves: list[MoveRecord] = []
        self.to_play = BLACK
        self.status = STATUS_PLAYING
        self.result: dict | None = None
        self.clocks = {
            BLACK: PlayerClock(cfg.time),
            WHITE: PlayerClock(cfg.time),
        }
        self._turn_started: float = time.monotonic()
        self.dead_stones: set[int] = set()
        self.score_preview: dict | None = None
        self.ai_thinking = False

    # ── 快照 ─────────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "mode": self.cfg.mode,
            "difficulty": self.cfg.difficulty,
            "ai_style": self.cfg.ai_style,
            "human_color": self.cfg.human_color,
            "ai_color": self.cfg.ai_color(),
            "komi": self.cfg.komi,
            "takeover": self.cfg.takeover,
            "review_source": (
                {"file": self.cfg.review_source[0], "moves": self.cfg.review_source[1]}
                if self.cfg.review_source
                else None
            ),
            "time": {
                "main": self.cfg.time.main_seconds,
                "byo": self.cfg.time.byo_seconds,
                "periods": self.cfg.time.byo_periods,
            },
            "names": {"black": self.cfg.black_name, "white": self.cfg.white_name},
            "status": self.status,
            "to_play": self.to_play,
            "board": list(self.board.grid),
            "size": self.board.size,
            "moves": [
                {
                    "n": m.n,
                    "color": m.color,
                    "point": m.point,
                    "captured": m.captured,
                    "clock_left": m.clock_left,
                }
                for m in self.moves
            ],
            "captures": {"black": self.board.captures[BLACK], "white": self.board.captures[WHITE]},
            "last_move": self.moves[-1].point if self.moves else None,
            "clocks": {str(c): self.clocks[c].snapshot() for c in (BLACK, WHITE)},
            "result": self.result,
            "dead_stones": sorted(self.dead_stones),
            "score_preview": self.score_preview,
            "ai_thinking": self.ai_thinking,
        }

    # ── 行棋 ─────────────────────────────────────────────

    def _check_turn(self, color: int) -> None:
        if self.status != STATUS_PLAYING:
            msg = "对局已结束"
            raise IllegalMove(msg, code="game.ended")
        if color != self.to_play:
            msg = "还没轮到这一方行棋"
            raise IllegalMove(msg, code="game.not_your_turn")

    def _settle_clock(self, color: int) -> float:
        """把本手耗时结算到行棋方时钟，返回剩余秒数（无限时为 -1）。

        日本式读秒：本手在读秒内完成即作废当前周期，下次轮到本方重新满额；
        只有周期在本回合内耗尽才扣读秒机会（同一回合可连扣多次）。
        """
        clock = self.clocks[color]
        if clock.unlimited:
            return -1.0
        elapsed = time.monotonic() - self._turn_started
        if not clock.in_byo:
            clock.main -= elapsed
            if clock.main < 0:
                # 主时耗尽 → 进入读秒，剩余时间转记到读秒
                clock.in_byo = True
                clock.byo_left = self.cfg.time.byo_seconds + clock.main
                clock.main = 0.0
                if clock.byo_left <= 0:
                    clock.byo_left = 0.0
                    self._consume_period(color)
        else:
            clock.byo_left -= elapsed
            if clock.byo_left < 0:
                clock.byo_left = 0.0
                self._consume_period(color)
        if clock.in_byo and self.status != STATUS_ENDED:
            # 读秒内落子 → 当前周期作废，下回合重新满额计时
            clock.byo_left = float(self.cfg.time.byo_seconds)
        remaining = clock.byo_left if clock.in_byo else clock.main
        self._turn_started = time.monotonic()
        return max(remaining, 0.0)

    def _consume_period(self, color: int) -> bool:
        """读秒周期耗尽：扣一次读秒机会。返回是否已判负。"""
        clock = self.clocks[color]
        if clock.periods_left > 0:
            clock.periods_left -= 1
        if clock.periods_left <= 0:
            self._end(opponent(color), "timeout")
            return True
        clock.byo_left = float(self.cfg.time.byo_seconds)
        return False

    def play(self, color: int, point: int) -> MoveRecord:
        self._check_turn(color)
        self._settle_clock(color)
        if self.status == STATUS_ENDED:  # 落子瞬间恰好超时
            msg = "超时判负"
            raise IllegalMove(msg, code="game.ended_by_timeout")
        r = self.board.play(color, point)
        return self._record(color, r.point, r.captured)

    def pass_move(self, color: int) -> MoveRecord:
        self._check_turn(color)
        self._settle_clock(color)
        if self.status == STATUS_ENDED:
            msg = "超时判负"
            raise IllegalMove(msg, code="game.ended_by_timeout")
        self.board.play(color, None)
        rec = self._record(color, None, [])
        if self.board.is_over_by_passes():
            self.status = STATUS_SCORING  # 等待引擎点目/玩家确认
        return rec

    def _record(self, color: int, point: int | None, captured: list[int]) -> MoveRecord:
        clock = self.clocks[color]
        left = clock.byo_left if clock.in_byo else clock.main
        left_out = -1.0 if clock.unlimited else left
        rec = MoveRecord(len(self.moves) + 1, color, point, captured, left_out)
        self.moves.append(rec)
        self.to_play = opponent(color)
        self._after_move()
        return rec

    def _after_move(self) -> None:
        """钩子：由 main.py 触发 AI 思考 / 广播。"""

    def resign(self, color: int) -> None:
        if self.status == STATUS_ENDED:
            return
        self._settle_clock(color)
        self._end(opponent(color), "resign")

    # ── 悔棋 ─────────────────────────────────────────────

    def undo(self) -> int:
        """悔棋：人人退 1 手；人机退到再次轮到人类行棋。

        返回退掉的手数；0 表示无法悔棋（点目阶段先 resume 返回对弈）。
        """
        if self.status != STATUS_PLAYING or not self.moves:
            return 0
        count = 0
        if self.cfg.mode == MODE_AI:
            human = self.cfg.human_color
            if not any(m.color == human for m in self.moves):
                return 0  # 人类还没下过子，无可悔
            # 先撤掉末尾连续的 AI 手，再撤掉人类最后一手 → 轮到人类重下
            while self.moves and self.moves[-1].color != human:
                self.moves.pop()
                count += 1
            self.moves.pop()
            count += 1
        else:
            self.moves.pop()
            count = 1
        self._rebuild()
        return count

    def _rebuild(self) -> None:
        """按剩余手数重放棋盘。"""
        self.board = Board(size=self.cfg.size, komi=self.cfg.komi)
        for m in self.moves:
            self.board.play(m.color, m.point)
        self.to_play = opponent(self.moves[-1].color) if self.moves else BLACK
        self._turn_started = time.monotonic()

    def seed_moves(self, moves: list[tuple[int, int | None]]) -> None:
        """复盘接管：以棋谱前缀开局（黑白轮转由棋谱保证；非法谱抛 IllegalMove）。

        建议配合不限时（free）时钟使用——接管后的手数不计时。
        """
        for color, point in moves:
            r = self.board.play(color, point)
            self.moves.append(MoveRecord(len(self.moves) + 1, color, point, r.captured, -1.0))
        self.to_play = opponent(moves[-1][0]) if moves else BLACK
        self._turn_started = time.monotonic()

    # ── 计时驱动 ─────────────────────────────────────────

    def tick(self) -> bool:
        """周期调用：检查当前行棋方是否超时。返回状态是否变化。"""
        if self.status != STATUS_PLAYING:
            return False
        clock = self.clocks[self.to_play]
        if clock.unlimited:
            return False
        elapsed = time.monotonic() - self._turn_started
        if not clock.in_byo:
            if clock.main - elapsed > 0:
                return False
            # 主时耗尽 → 进入读秒（本手内继续），溢出时间计入读秒
            overage = max(elapsed - clock.main, 0.0)
            clock.in_byo = True
            clock.main = 0.0
            clock.byo_left = self.cfg.time.byo_seconds - overage
            self._turn_started = time.monotonic()
            if clock.byo_left <= 0:
                clock.byo_left = 0.0
                if self._consume_period(self.to_play):
                    return True
            return True
        if clock.byo_left - elapsed > 0:
            return False
        clock.byo_left = 0.0
        self._turn_started = time.monotonic()
        if self._consume_period(self.to_play):
            return True
        return True

    def clock_view(self) -> dict:
        """实时剩余时间（含未结算的本手耗时）。"""
        out = {}
        for c in (BLACK, WHITE):
            clock = self.clocks[c]
            if clock.unlimited:
                out[str(c)] = {**clock.snapshot(), "display": -1}
                continue
            if c == self.to_play and self.status == STATUS_PLAYING:
                elapsed = time.monotonic() - self._turn_started
                if clock.in_byo:
                    disp = max(clock.byo_left - elapsed, 0.0)
                else:
                    disp = max(clock.main - elapsed, 0.0)
            else:
                disp = clock.byo_left if clock.in_byo else clock.main
            out[str(c)] = {**clock.snapshot(), "display": disp}
        return out

    # ── 终局点目 ─────────────────────────────────────────

    def request_scoring(self) -> bool:
        """对弈中主动点目：立即进入点目阶段（无需双停一手）。

        死子判定与预览由随后的引擎分析给出（enter_scoring）；
        返回是否发生状态转移（已在点目/已终局时为 False，幂等）。
        """
        if self.status != STATUS_PLAYING:
            return False
        self.status = STATUS_SCORING
        self.dead_stones = set()
        self.score_preview = None  # 引擎判定完成前不给出预览
        return True

    def resume(self) -> bool:
        """拒绝点目结果：返回对弈。手数不动，点目审查时间不计入时钟。"""
        if self.status != STATUS_SCORING:
            return False
        self.status = STATUS_PLAYING
        self.dead_stones.clear()
        self.score_preview = None
        self._turn_started = time.monotonic()
        return True

    def enter_scoring(self, dead_stones: set[int]) -> None:
        """双方停一手后，用引擎 ownership 给出死子判定与点目预览。"""
        self.status = STATUS_SCORING
        self.dead_stones = dead_stones
        self._refresh_score()

    def set_dead_stones(self, points: set[int]) -> None:
        if self.status != STATUS_SCORING:
            msg = "不在点目阶段"
            raise IllegalMove(msg, code="scoring.not_active")
        self.dead_stones = points
        self._refresh_score()

    def _refresh_score(self) -> None:
        s = self.board.score(self.dead_stones)
        # 文案由前端按 winner/margin/black_area/white_area 本地化组合
        self.score_preview = {
            "black_area": s.black_area,
            "white_area": s.white_area,
            "winner": s.winner,
            "margin": s.margin,
            "ownership": s.ownership,  # 1黑 2白 0中立（点目视角）
        }

    def confirm_score(self) -> dict:
        """确认点目 → 终局。"""
        if self.status != STATUS_SCORING:
            msg = "不在点目阶段"
            raise IllegalMove(msg, code="scoring.not_active")
        s = self.board.score(self.dead_stones)
        self._end(s.winner, "score", s.margin)
        return self.result or {}

    def _end(self, winner: int | None, reason: str, margin: float = 0.0) -> None:
        self.status = STATUS_ENDED
        self.ai_thinking = False
        self.result = {
            "winner": winner,
            "reason": reason,
            "margin": margin,
            "sgf_result": result_string(winner, reason, margin),
        }

    def to_sgf(self) -> SgfGame:
        cfg = self.cfg
        names = {
            BLACK: cfg.black_name,
            WHITE: cfg.white_name,
        }
        ai_color = cfg.ai_color()
        if ai_color:
            names[ai_color] = f"KataGo ({cfg.difficulty}, {cfg.ai_style})"
        return SgfGame(
            size=self.board.size,
            komi=cfg.komi,
            black_name=names[BLACK],
            white_name=names[WHITE],
            date=datetime.now().strftime("%Y-%m-%d"),
            result=(self.result or {}).get("sgf_result", "?"),
            main_time=cfg.time.main_seconds,
            byo_seconds=cfg.time.byo_seconds,
            byo_periods=cfg.time.byo_periods,
            moves=[(m.color, m.point) for m in self.moves],
            time_left=[m.clock_left for m in self.moves],
        )
