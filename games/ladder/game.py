"""사다리타기 게임 — 순수 게임 로직 (Slack 의존 없음)."""

import random
from dataclasses import dataclass, field
from enum import Enum

LOSER_LABEL = "커피사기"
WINNER_LABEL = "통과"


class Phase(Enum):
    LOBBY = "lobby"
    DONE = "done"


@dataclass
class Game:
    channel: str
    creator: str
    players: list[str] = field(default_factory=list)
    phase: Phase = Phase.LOBBY
    thread_ts: str | None = None
    result: dict[str, str] = field(default_factory=dict)
    ladder_text: str = ""

    def to_dict(self) -> dict:
        return {
            "game_type": "ladder",
            "channel": self.channel,
            "creator": self.creator,
            "players": self.players,
            "phase": self.phase.value,
            "thread_ts": self.thread_ts,
            "result": self.result,
            "ladder_text": self.ladder_text,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Game":
        return cls(
            channel=d["channel"],
            creator=d["creator"],
            players=d["players"],
            phase=Phase(d["phase"]),
            thread_ts=d["thread_ts"],
            result=d.get("result", {}),
            ladder_text=d.get("ladder_text", ""),
        )


def generate_rungs(n: int) -> list[tuple[int, int]]:
    """N열 사다리의 가로대 목록을 반환.

    각 가로대는 (row, left_col) 형태로, left_col 과 left_col+1 을 연결.
    같은 행에서 인접한 가로대는 생성하지 않음.
    """
    n_rows = max(6, n * 3)
    rungs: list[tuple[int, int]] = []
    for row in range(n_rows):
        occupied: set[int] = set()
        for col in random.sample(range(n - 1), n - 1):
            if col not in occupied and (col + 1) not in occupied:
                if random.random() < 0.4:
                    rungs.append((row, col))
                    occupied.add(col)
                    occupied.add(col + 1)
    return rungs


def simulate_path(rungs: list[tuple[int, int]], n_rows: int, start: int) -> int:
    """start 열에서 출발해 사다리를 내려간 최종 열 반환."""
    col = start
    for row in range(n_rows):
        for r, c in rungs:
            if r == row:
                if c == col:
                    col += 1
                    break
                elif c + 1 == col:
                    col -= 1
                    break
    return col


def format_ladder(
    n: int,
    n_rows: int,
    rungs: list[tuple[int, int]],
    col_labels: list[str],
) -> str:
    """사다리 텍스트 아트 생성."""
    rung_set = set(rungs)
    lines: list[str] = []

    # 상단 번호 (각 열 간격 4칸: |   |   |)
    header = "".join(f"{i + 1:<4}" for i in range(n - 1)) + str(n)
    lines.append(header)

    # 사다리 본체
    for row in range(n_rows):
        row_rungs = {c for r, c in rung_set if r == row}
        segs = ["|"]
        for col in range(n - 1):
            segs.append("---|" if col in row_rungs else "   |")
        lines.append("".join(segs))

    # 하단 결과 레이블
    footer_parts = []
    for label in col_labels:
        # 4칸 너비로 맞추되, 레이블이 길면 잘라서 표시
        footer_parts.append(f"{label:<4}")
    lines.append("".join(footer_parts).rstrip())

    return "\n".join(lines)


def run_game(players: list[str]) -> tuple[dict[str, str], str]:
    """사다리 게임 실행.

    Returns:
        (result, ladder_text)
        result: 플레이어 ID → 결과 레이블
        ladder_text: 사다리 텍스트 아트
    """
    n = len(players)
    n_rows = max(6, n * 3)
    rungs = generate_rungs(n)

    # 각 열의 최종 도착 위치 계산
    final_cols = [simulate_path(rungs, n_rows, i) for i in range(n)]

    # 하단 레이블: 한 칸만 커피사기
    loser_bottom = random.randint(0, n - 1)
    col_labels = [WINNER_LABEL] * n
    col_labels[loser_bottom] = LOSER_LABEL

    result = {players[i]: col_labels[final_cols[i]] for i in range(n)}
    ladder_text = format_ladder(n, n_rows, rungs, col_labels)
    return result, ladder_text
