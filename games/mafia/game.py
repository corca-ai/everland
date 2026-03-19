"""마피아 게임 — 순수 게임 로직 (Slack 의존 없음)."""

import random
import threading
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

VOTE_TIMEOUT = 5 * 60  # 5분


class Phase(Enum):
    LOBBY = "lobby"
    NIGHT = "night"
    DAY = "day"


@dataclass
class Game:
    channel: str
    creator: str
    players: list[str] = field(default_factory=list)
    mafia: list[str] = field(default_factory=list)
    citizens: list[str] = field(default_factory=list)
    alive: list[str] = field(default_factory=list)
    phase: Phase = Phase.LOBBY
    night_votes: dict[str, str] = field(default_factory=dict)
    day_votes: dict[str, str] = field(default_factory=dict)
    thread_ts: str | None = None
    timer: threading.Timer | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    doctors: list[str] = field(default_factory=list)
    polices: list[str] = field(default_factory=list)
    doctor_targets: dict[str, str] = field(default_factory=dict)
    police_targets: dict[str, str] = field(default_factory=dict)
    runoff_targets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "game_type": "mafia",
            "channel": self.channel,
            "creator": self.creator,
            "players": self.players,
            "mafia": self.mafia,
            "citizens": self.citizens,
            "alive": self.alive,
            "phase": self.phase.value,
            "night_votes": self.night_votes,
            "day_votes": self.day_votes,
            "thread_ts": self.thread_ts,
            "doctors": self.doctors,
            "polices": self.polices,
            "doctor_targets": self.doctor_targets,
            "police_targets": self.police_targets,
            "runoff_targets": self.runoff_targets,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Game":
        return cls(
            channel=d["channel"],
            creator=d["creator"],
            players=d["players"],
            mafia=d["mafia"],
            citizens=d["citizens"],
            alive=d["alive"],
            phase=Phase(d["phase"]),
            night_votes=d["night_votes"],
            day_votes=d["day_votes"],
            thread_ts=d["thread_ts"],
            doctors=d.get("doctors", []),
            polices=d.get("polices", []),
            doctor_targets=d.get("doctor_targets", {}),
            police_targets=d.get("police_targets", {}),
            runoff_targets=d.get("runoff_targets", []),
        )


def mafia_count(player_count: int) -> int:
    if player_count <= 5:
        return 1
    if player_count <= 8:
        return 2
    if player_count <= 11:
        return 3
    return 4


def special_count(player_count: int) -> tuple[int, int]:
    """인원수에 따른 (의사 수, 경찰 수) 반환."""
    if player_count < 6:
        return 0, 0
    if player_count <= 11:
        return 1, 1
    if player_count <= 14:
        return 2, 1
    return 2, 2


def role_name(game: Game, player: str) -> str:
    if player in game.mafia:
        return "마피아"
    if player in game.doctors:
        return "의사"
    if player in game.polices:
        return "경찰"
    return "시민"


def check_win(game: Game) -> str | None:
    alive_mafia = [p for p in game.alive if p in game.mafia]
    alive_citizens = [p for p in game.alive if p in game.citizens]
    if not alive_mafia:
        return "citizen"
    if len(alive_mafia) >= len(alive_citizens):
        return "mafia"
    return None


def night_all_done(game: Game) -> bool:
    """밤 행동이 모두 완료되었는지 확인."""
    alive_mafia = [m for m in game.mafia if m in game.alive]
    if not all(m in game.night_votes for m in alive_mafia):
        return False
    alive_docs = [d for d in game.doctors if d in game.alive]
    if not all(d in game.doctor_targets for d in alive_docs):
        return False
    alive_cops = [c for c in game.polices if c in game.alive]
    if not all(c in game.police_targets for c in alive_cops):
        return False
    return True


def assign_roles(players: list[str]) -> Game:
    """플레이어 목록으로 역할을 배정한 Game을 반환. channel/creator는 빈 값."""
    n = len(players)
    n_mafia = mafia_count(n)
    n_doc, n_cop = special_count(n)
    shuffled = players[:]
    random.shuffle(shuffled)
    mafia = shuffled[:n_mafia]
    citizens = shuffled[n_mafia:]
    doctors = citizens[:n_doc]
    polices = citizens[n_doc : n_doc + n_cop]
    return Game(
        channel="",
        creator="",
        players=players[:],
        mafia=mafia,
        citizens=citizens,
        alive=players[:],
        doctors=doctors,
        polices=polices,
    )


def tally_votes(votes: dict[str, str], skip_value: str | None = None) -> Counter[str]:
    """투표를 집계해 Counter로 반환. skip_value에 해당하는 값은 제외."""
    return Counter(v for v in votes.values() if v != skip_value)


def resolve_night_votes(game: Game) -> tuple[str | None, bool]:
    """밤 투표를 해석해 (피해자, 보호 여부)를 반환.

    투표가 없으면 (None, False).
    의사가 보호했으면 (피해자, True).
    그 외 (피해자, False).
    """
    if not game.night_votes:
        return None, False

    counts = tally_votes(game.night_votes)
    max_votes = max(counts.values())
    top = [t for t, c in counts.items() if c == max_votes]
    victim = random.choice(top)

    protected = set(game.doctor_targets.values())
    if victim in protected:
        return victim, True

    return victim, False


def resolve_day_votes(game: Game) -> str | list[str] | None:
    """낮 투표를 해석해 결과를 반환.

    - 투표가 없으면 None
    - 단독 1위면 해당 플레이어 ID (str)
    - 동률이면 동률 대상 리스트 (list[str])
    """
    counts = tally_votes(game.day_votes, skip_value="skip")
    if not counts:
        return None

    max_votes = max(counts.values())
    top = [t for t, c in counts.items() if c == max_votes]

    if len(top) == 1:
        return top[0]
    return top


def has_majority(game: Game) -> str | None:
    """과반수 득표자가 있으면 해당 플레이어 ID, 없으면 None."""
    counts = tally_votes(game.day_votes, skip_value="skip")
    majority = len(game.alive) // 2 + 1
    for target, count in counts.items():
        if count >= majority:
            return target
    return None
