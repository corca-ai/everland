"""games.ladder.game 순수 로직 테스트."""

import random

from games.ladder.game import (
    LOSER_LABEL,
    WINNER_LABEL,
    Game,
    Phase,
    format_ladder,
    generate_rungs,
    run_game,
    simulate_path,
)

# ─── generate_rungs ───


def test_generate_rungs_no_adjacent_in_same_row():
    """같은 행에서 인접한 가로대가 없어야 한다."""
    random.seed(0)
    rungs = generate_rungs(5)
    by_row: dict[int, list[int]] = {}
    for row, col in rungs:
        by_row.setdefault(row, []).append(col)
    for row, cols in by_row.items():
        col_set = set(cols)
        for col in cols:
            assert col + 1 not in col_set, f"행 {row}에 인접 가로대 존재: {col}, {col + 1}"


def test_generate_rungs_valid_columns():
    """가로대 열 인덱스가 유효한 범위(0 ~ n-2)여야 한다."""
    n = 4
    random.seed(42)
    rungs = generate_rungs(n)
    for _, col in rungs:
        assert 0 <= col < n - 1


def test_generate_rungs_single_player_empty():
    """1명이면 가로대가 없다."""
    rungs = generate_rungs(1)
    assert rungs == []


# ─── simulate_path ───


def test_simulate_path_no_rungs():
    """가로대 없으면 시작 열 = 도착 열."""
    for i in range(4):
        assert simulate_path([], 6, i) == i


def test_simulate_path_moves_right():
    """가로대 왼쪽 열에서 출발하면 오른쪽으로 이동."""
    rungs = [(0, 1)]  # row=0, col=1↔2
    assert simulate_path(rungs, 6, 1) == 2


def test_simulate_path_moves_left():
    """가로대 오른쪽 열에서 출발하면 왼쪽으로 이동."""
    rungs = [(0, 1)]  # row=0, col=1↔2
    assert simulate_path(rungs, 6, 2) == 1


def test_simulate_path_unaffected_column():
    """가로대와 무관한 열은 그대로."""
    rungs = [(0, 1)]
    assert simulate_path(rungs, 6, 0) == 0
    assert simulate_path(rungs, 6, 3) == 3


def test_simulate_path_multiple_rungs():
    """연속 가로대를 따라 올바르게 이동."""
    # row=0: col=0↔1, row=1: col=1↔2
    rungs = [(0, 0), (1, 1)]
    # 0열 → row0에서 오른쪽 → 1열 → row1에서 오른쪽 → 2열
    assert simulate_path(rungs, 6, 0) == 2


# ─── run_game ───


def test_run_game_exactly_one_loser():
    """결과에서 커피사기는 정확히 1명이어야 한다."""
    random.seed(7)
    players = ["a", "b", "c", "d"]
    result, _ = run_game(players)
    losers = [p for p, label in result.items() if label == LOSER_LABEL]
    winners = [p for p, label in result.items() if label == WINNER_LABEL]
    assert len(losers) == 1
    assert len(winners) == len(players) - 1


def test_run_game_all_players_have_result():
    """모든 플레이어가 결과를 받아야 한다."""
    random.seed(99)
    players = ["x", "y", "z"]
    result, _ = run_game(players)
    assert set(result.keys()) == set(players)


def test_run_game_two_players():
    """2명 최소 인원도 동작해야 한다."""
    random.seed(1)
    result, ladder_text = run_game(["p1", "p2"])
    assert len(result) == 2
    assert ladder_text != ""


def test_run_game_returns_ladder_text():
    """ladder_text가 비어있지 않아야 한다."""
    random.seed(3)
    _, ladder_text = run_game(["a", "b", "c"])
    assert ladder_text.strip() != ""


# ─── format_ladder ───


def test_format_ladder_contains_numbers():
    """사다리 헤더에 열 번호가 포함되어야 한다."""
    n = 3
    text = format_ladder(n, 6, [], [WINNER_LABEL, LOSER_LABEL, WINNER_LABEL])
    assert "1" in text
    assert "2" in text
    assert "3" in text


def test_format_ladder_contains_labels():
    """사다리 하단에 결과 레이블이 포함되어야 한다."""
    labels = [WINNER_LABEL, LOSER_LABEL, WINNER_LABEL]
    text = format_ladder(3, 6, [], labels)
    assert LOSER_LABEL in text
    assert WINNER_LABEL in text


def test_format_ladder_rung_appears():
    """가로대가 있는 경우 '---'가 텍스트에 포함되어야 한다."""
    rungs = [(0, 0)]
    text = format_ladder(3, 6, rungs, [WINNER_LABEL] * 3)
    assert "---" in text


def test_format_ladder_no_rung_no_dashes():
    """가로대가 없으면 '---'가 텍스트에 없어야 한다."""
    text = format_ladder(3, 6, [], [WINNER_LABEL] * 3)
    assert "---" not in text


# ─── Game serialization ───


def test_to_dict_from_dict_roundtrip():
    game = Game(
        channel="C1",
        creator="u1",
        players=["u1", "u2"],
        phase=Phase.DONE,
        thread_ts="123.456",
        result={"u1": WINNER_LABEL, "u2": LOSER_LABEL},
        ladder_text="sample",
    )
    d = game.to_dict()
    assert d["game_type"] == "ladder"
    restored = Game.from_dict(d)
    assert restored.channel == game.channel
    assert restored.creator == game.creator
    assert restored.players == game.players
    assert restored.phase == game.phase
    assert restored.thread_ts == game.thread_ts
    assert restored.result == game.result
    assert restored.ladder_text == game.ladder_text


def test_from_dict_missing_optional_fields():
    """optional 필드가 없어도 복원 가능해야 한다."""
    d = {
        "game_type": "ladder",
        "channel": "C2",
        "creator": "u1",
        "players": [],
        "phase": "lobby",
        "thread_ts": None,
    }
    game = Game.from_dict(d)
    assert game.result == {}
    assert game.ladder_text == ""
