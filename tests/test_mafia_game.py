"""games.mafia.game 순수 로직 테스트."""

import random

from games.mafia.game import (
    Game,
    Phase,
    assign_roles,
    check_win,
    has_majority,
    mafia_count,
    night_all_done,
    resolve_day_votes,
    resolve_night_votes,
    role_name,
    special_count,
    tally_votes,
)

# ─── 헬퍼 ───

PLAYERS = ["p1", "p2", "p3", "p4", "p5"]


def make_game(**overrides) -> Game:
    defaults = dict(
        channel="C1",
        creator="p1",
        players=PLAYERS[:],
        mafia=["p1"],
        citizens=["p2", "p3", "p4", "p5"],
        alive=PLAYERS[:],
        phase=Phase.NIGHT,
        doctors=[],
        polices=[],
    )
    defaults.update(overrides)
    return Game(**defaults)


# ─── mafia_count ───


def test_mafia_count():
    assert mafia_count(4) == 1
    assert mafia_count(5) == 1
    assert mafia_count(6) == 2
    assert mafia_count(8) == 2
    assert mafia_count(9) == 3
    assert mafia_count(11) == 3
    assert mafia_count(12) == 4


# ─── special_count ───


def test_special_count():
    assert special_count(4) == (0, 0)
    assert special_count(5) == (0, 0)
    assert special_count(6) == (1, 1)
    assert special_count(11) == (1, 1)
    assert special_count(12) == (2, 1)
    assert special_count(14) == (2, 1)
    assert special_count(15) == (2, 2)


# ─── role_name ───


def test_role_name():
    game = make_game(doctors=["p2"], polices=["p3"])
    assert role_name(game, "p1") == "마피아"
    assert role_name(game, "p2") == "의사"
    assert role_name(game, "p3") == "경찰"
    assert role_name(game, "p4") == "시민"


# ─── check_win ───


def test_citizen_win_when_no_mafia_alive():
    game = make_game(alive=["p2", "p3", "p4"])
    assert check_win(game) == "citizen"


def test_mafia_win_when_equal_or_more():
    game = make_game(alive=["p1", "p2"])
    assert check_win(game) == "mafia"


def test_no_winner_yet():
    game = make_game(alive=["p1", "p2", "p3"])
    assert check_win(game) is None


# ─── night_all_done ───


def test_night_all_done_no_specials():
    game = make_game(night_votes={"p1": "p2"})
    assert night_all_done(game) is True


def test_night_not_done_missing_mafia_vote():
    game = make_game(night_votes={})
    assert night_all_done(game) is False


def test_night_all_done_with_specials():
    game = make_game(
        doctors=["p2"],
        polices=["p3"],
        night_votes={"p1": "p4"},
        doctor_targets={"p2": "p4"},
        police_targets={"p3": "p1"},
    )
    assert night_all_done(game) is True


def test_night_not_done_missing_doctor():
    game = make_game(
        doctors=["p2"],
        night_votes={"p1": "p4"},
        doctor_targets={},
    )
    assert night_all_done(game) is False


def test_night_done_dead_doctor_skipped():
    game = make_game(
        alive=["p1", "p3", "p4", "p5"],
        doctors=["p2"],
        night_votes={"p1": "p3"},
    )
    # p2 is dead, so doctor vote is not needed
    assert night_all_done(game) is True


# ─── tally_votes ───


def test_tally_votes():
    votes = {"p1": "p3", "p2": "p3", "p4": "p5"}
    counts = tally_votes(votes)
    assert counts["p3"] == 2
    assert counts["p5"] == 1


def test_tally_votes_skip():
    votes = {"p1": "p3", "p2": "skip", "p4": "p3"}
    counts = tally_votes(votes, skip_value="skip")
    assert counts["p3"] == 2
    assert "skip" not in counts


# ─── resolve_night_votes ───


def test_resolve_night_no_votes():
    game = make_game(night_votes={})
    victim, protected = resolve_night_votes(game)
    assert victim is None
    assert protected is False


def test_resolve_night_kill():
    random.seed(42)
    game = make_game(night_votes={"p1": "p3"})
    victim, protected = resolve_night_votes(game)
    assert victim == "p3"
    assert protected is False


def test_resolve_night_doctor_saves():
    random.seed(42)
    game = make_game(
        night_votes={"p1": "p3"},
        doctor_targets={"p2": "p3"},
    )
    victim, protected = resolve_night_votes(game)
    assert victim == "p3"
    assert protected is True


# ─── resolve_day_votes ───


def test_resolve_day_no_votes():
    game = make_game(phase=Phase.DAY, day_votes={})
    assert resolve_day_votes(game) is None


def test_resolve_day_all_skip():
    game = make_game(phase=Phase.DAY, day_votes={"p1": "skip", "p2": "skip"})
    assert resolve_day_votes(game) is None


def test_resolve_day_clear_winner():
    game = make_game(phase=Phase.DAY, day_votes={"p2": "p1", "p3": "p1", "p4": "p5"})
    assert resolve_day_votes(game) == "p1"


def test_resolve_day_tie():
    game = make_game(phase=Phase.DAY, day_votes={"p2": "p1", "p3": "p4"})
    result = resolve_day_votes(game)
    assert isinstance(result, list)
    assert set(result) == {"p1", "p4"}


# ─── has_majority ───


def test_has_majority_yes():
    game = make_game(phase=Phase.DAY, day_votes={"p2": "p1", "p3": "p1", "p4": "p1"})
    assert has_majority(game) == "p1"


def test_has_majority_no():
    game = make_game(phase=Phase.DAY, day_votes={"p2": "p1", "p3": "p4"})
    assert has_majority(game) is None


def test_has_majority_skip_not_counted():
    game = make_game(
        phase=Phase.DAY,
        alive=["p1", "p2", "p3"],
        day_votes={"p1": "skip", "p2": "skip", "p3": "p1"},
    )
    # majority = 2, p1 has 1 vote
    assert has_majority(game) is None


# ─── assign_roles ───


def test_assign_roles_4_players():
    random.seed(0)
    game = assign_roles(["a", "b", "c", "d"])
    assert len(game.mafia) == 1
    assert len(game.citizens) == 3
    assert len(game.alive) == 4
    assert game.doctors == []
    assert game.polices == []
    assert set(game.mafia + game.citizens) == {"a", "b", "c", "d"}


def test_assign_roles_8_players():
    random.seed(0)
    players = [f"p{i}" for i in range(8)]
    game = assign_roles(players)
    assert len(game.mafia) == 2
    assert len(game.doctors) == 1
    assert len(game.polices) == 1


# ─── Game serialization ───


def test_to_dict_from_dict_roundtrip():
    game = make_game(doctors=["p2"], polices=["p3"], thread_ts="1234.5678")
    d = game.to_dict()
    restored = Game.from_dict(d)
    assert restored.channel == game.channel
    assert restored.mafia == game.mafia
    assert restored.doctors == game.doctors
    assert restored.polices == game.polices
    assert restored.phase == game.phase
    assert restored.thread_ts == game.thread_ts
