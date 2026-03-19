"""마피아 게임."""

import random
import threading
from dataclasses import dataclass, field
from enum import Enum

import db
from utils import C, log_header, log_event, log_phase, get_name, names, format_players, send_dm

VOTE_TIMEOUT = 10 * 60  # 10분


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
        )


# channel_id -> Game
sessions: dict[str, Game] = {}


def save(game: Game):
    db.save(game.channel, game.to_dict())


def mafia_count(player_count: int) -> int:
    if player_count <= 5:
        return 1
    if player_count <= 8:
        return 2
    if player_count <= 11:
        return 3
    return 4


def check_win(game: Game) -> str | None:
    alive_mafia = [p for p in game.alive if p in game.mafia]
    alive_citizens = [p for p in game.alive if p in game.citizens]
    if not alive_mafia:
        return "citizen"
    if len(alive_mafia) >= len(alive_citizens):
        return "mafia"
    return None


def cancel_timer(game: Game):
    if game.timer:
        game.timer.cancel()
        game.timer = None


def post(game: Game, client, text: str):
    client.chat_postMessage(channel=game.channel, thread_ts=game.thread_ts, text=text)


def log_status(game: Game, client):
    alive_mafia = [p for p in game.alive if p in game.mafia]
    alive_citizens = [p for p in game.alive if p in game.citizens]
    dead = [p for p in game.players if p not in game.alive]
    print(f"  {C.DIM}├ 생존 마피아: {C.RED}{names(alive_mafia, client)}{C.RESET}")
    print(f"  {C.DIM}├ 생존 시민:   {C.GREEN}{names(alive_citizens, client)}{C.RESET}")
    if dead:
        print(f"  {C.DIM}└ 사망:       {C.DIM}{names(dead, client)}{C.RESET}")


# ─── 핸들러 등록 ───


def register(app):
    app.command("/새게임")(new_game)
    app.command("/시작")(start_game)
    app.action("mafia_join_game")(handle_join)
    app.action("mafia_kill_select")(handle_mafia_vote)
    app.action("mafia_day_vote_select")(handle_day_vote)


def restore(client):
    saved = db.load_all()
    for channel, data in saved.items():
        if data.get("game_type") != "mafia":
            continue
        game = Game.from_dict(data)
        sessions[channel] = game
        log_event(f"{C.CYAN}복원[마피아]", f"채널 {channel} / {game.phase.value} / 생존 {len(game.alive)}명{C.RESET}")

        if game.phase == Phase.NIGHT:
            game.timer = threading.Timer(VOTE_TIMEOUT, night_timeout, args=[game, client])
            game.timer.daemon = True
            game.timer.start()
        elif game.phase == Phase.DAY:
            game.timer = threading.Timer(VOTE_TIMEOUT, day_timeout, args=[game, client])
            game.timer.daemon = True
            game.timer.start()


# ─── 슬래시 커맨드 ───


def new_game(ack, command, client):
    ack()
    channel = command["channel_id"]
    user = command["user_id"]

    if channel in sessions and sessions[channel].phase != Phase.LOBBY:
        client.chat_postMessage(channel=channel, text=":x: 이미 진행 중인 게임이 있습니다.")
        return

    game = Game(channel=channel, creator=user)
    sessions[channel] = game

    log_header(f"{C.YELLOW}새 마피아 게임{C.RESET}{C.BOLD} by {get_name(user, client)}")

    result = client.chat_postMessage(
        channel=channel,
        text=f"<@{user}>님이 마피아 게임을 열었습니다!",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"<@{user}>님이 *마피아 게임*을 열었습니다! :detective:\n"
                        "참여하려면 아래 버튼을 눌러주세요.\n\n"
                        "현재 참여자: 없음"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "참여하기"},
                        "style": "primary",
                        "action_id": "mafia_join_game",
                    }
                ],
            },
        ],
    )
    game.thread_ts = result["ts"]
    save(game)


def start_game(ack, command, client):
    ack()
    channel = command["channel_id"]
    user = command["user_id"]

    game = sessions.get(channel)
    if not game:
        client.chat_postMessage(channel=channel, text=":x: 열린 게임이 없습니다. `/새게임`으로 먼저 게임을 만들어주세요.")
        return
    if game.phase != Phase.LOBBY:
        client.chat_postMessage(channel=channel, text=":x: 이미 게임이 진행 중입니다.")
        return
    if game.creator != user:
        client.chat_postMessage(channel=channel, text=":x: 게임을 만든 사람만 시작할 수 있습니다.")
        return
    if len(game.players) < 4:
        client.chat_postMessage(channel=channel, text=":x: 최소 4명이 필요합니다.")
        return

    n_mafia = mafia_count(len(game.players))
    shuffled = game.players[:]
    random.shuffle(shuffled)
    game.mafia = shuffled[:n_mafia]
    game.citizens = shuffled[n_mafia:]
    game.alive = game.players[:]

    mafia_names_str = format_players(game.mafia)

    log_header(f"{C.GREEN}게임 시작!{C.RESET}{C.BOLD} ({len(game.players)}명)")
    log_event(f"{C.RED}마피아", f"{names(game.mafia, client)}{C.RESET}")
    log_event(f"{C.GREEN}시  민", f"{names(game.citizens, client)}{C.RESET}")

    for player in game.players:
        if player in game.mafia:
            send_dm(client, player, f":smiling_imp: 당신은 *마피아*입니다!\n동료 마피아: {mafia_names_str}")
        else:
            send_dm(client, player, ":innocent: 당신은 *시민*입니다.\n마피아를 찾아내세요!")

    post(
        game,
        client,
        f":game_die: 게임이 시작됩니다! 참여자 {len(game.players)}명, 마피아 {n_mafia}명\n역할이 DM으로 전달되었습니다.",
    )

    start_night(game, client)


# ─── 참여 ───


def handle_join(ack, body, client):
    ack()
    channel = body["channel"]["id"]
    user = body["user"]["id"]

    game = sessions.get(channel)
    if not game or game.phase != Phase.LOBBY:
        return

    if user in game.players:
        client.chat_postEphemeral(channel=channel, user=user, text="이미 참여했습니다.")
        return

    game.players.append(user)
    player_list = format_players(game.players)

    log_event(f"{C.CYAN}+참여", f"{get_name(user, client)} (현재 {len(game.players)}명){C.RESET}")

    client.chat_update(
        channel=channel,
        ts=game.thread_ts,
        text=f"마피아 게임 참여자 모집 중! 현재 {len(game.players)}명",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*마피아 게임* 참여자 모집 중! :detective:\n"
                        "참여하려면 아래 버튼을 눌러주세요.\n\n"
                        f"현재 참여자 ({len(game.players)}명): {player_list}"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "참여하기"},
                        "style": "primary",
                        "action_id": "mafia_join_game",
                    }
                ],
            },
        ],
    )
    save(game)


# ─── 밤 ───


def start_night(game: Game, client):
    game.phase = Phase.NIGHT
    game.night_votes = {}
    save(game)

    log_phase(f"{C.BLUE}밤이 되었습니다{C.RESET}")
    log_status(game, client)

    alive_mafia = [m for m in game.mafia if m in game.alive]
    log_event(f"{C.RED}마피아 투표 대기 중...", f"{names(alive_mafia, client)}{C.RESET}")

    post(game, client, ":night_with_stars: *밤이 되었습니다.* 마피아가 활동합니다... 모두 잠드세요. (10분 제한)")

    options = [
        {"text": {"type": "plain_text", "text": f"<@{p}>"}, "value": p}
        for p in game.alive
        if p not in game.mafia
    ]
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":night_with_stars: *밤이 되었습니다.*\n죽일 사람을 선택하세요. (10분 제한)"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "static_select",
                    "placeholder": {"type": "plain_text", "text": "대상 선택"},
                    "options": options,
                    "action_id": "mafia_kill_select",
                }
            ],
        },
    ]

    for m in alive_mafia:
        send_dm(client, m, "밤입니다. 죽일 사람을 선택하세요.", blocks=blocks)

    game.timer = threading.Timer(VOTE_TIMEOUT, night_timeout, args=[game, client])
    game.timer.daemon = True
    game.timer.start()


def night_timeout(game: Game, client):
    with game.lock:
        if game.phase != Phase.NIGHT:
            return
        log_event(f"{C.RED}시간 초과", f"밤 투표 10분 경과{C.RESET}")
        resolve_night(game, client)


def handle_mafia_vote(ack, body, client):
    ack()
    user = body["user"]["id"]
    selected = body["actions"][0]["selected_option"]["value"]

    game = None
    for g in sessions.values():
        if user in g.mafia and g.phase == Phase.NIGHT:
            game = g
            break
    if not game:
        return

    with game.lock:
        if game.phase != Phase.NIGHT:
            return

        game.night_votes[user] = selected
        save(game)

        log_event(
            f"{C.RED}마피아 투표",
            f"{get_name(user, client)} → {C.BOLD}{get_name(selected, client)}{C.RESET}",
        )

        send_dm(client, user, f":knife: <@{selected}>을(를) 선택했습니다.")

        alive_mafia = [m for m in game.mafia if m in game.alive]
        if all(m in game.night_votes for m in alive_mafia):
            cancel_timer(game)
            resolve_night(game, client)


def resolve_night(game: Game, client):
    if not game.night_votes:
        log_event(f"{C.DIM}결과", f"투표 없음 - 아무도 죽지 않음{C.RESET}")
        post(game, client, ":sunrise: *아침이 밝았습니다.*\n간밤에는 아무 일도 일어나지 않았습니다.")
        start_day(game, client)
        return

    vote_counts: dict[str, int] = {}
    for target in game.night_votes.values():
        vote_counts[target] = vote_counts.get(target, 0) + 1

    max_votes = max(vote_counts.values())
    top_targets = [t for t, c in vote_counts.items() if c == max_votes]
    victim = random.choice(top_targets)

    game.alive.remove(victim)
    save(game)

    role = "마피아" if victim in game.mafia else "시민"

    log_phase(f"{C.YELLOW}아침이 밝았습니다{C.RESET}")
    log_event(f"{C.RED}사망", f"{C.BOLD}{get_name(victim, client)}{C.RESET} ({role}) - 마피아에 의해 살해됨")

    post(game, client, f":sunrise: *아침이 밝았습니다.*\n\n:skull: <@{victim}>님이 마피아에 의해 살해당했습니다. (정체: {role})")

    winner = check_win(game)
    if winner:
        end_game(game, winner, client)
        return

    start_day(game, client)


# ─── 낮 ───


def start_day(game: Game, client):
    game.phase = Phase.DAY
    game.day_votes = {}
    save(game)

    log_phase(f"{C.YELLOW}낮 - 투표 시간{C.RESET}")
    log_status(game, client)
    log_event(f"{C.YELLOW}투표 대기 중...", f"{names(game.alive, client)}{C.RESET}")

    alive_list = format_players(game.alive)
    post(
        game,
        client,
        (
            f":speaking_head_in_silhouette: *낮입니다.* 스레드에서 토론하세요!\n"
            f"DM으로 투표가 전송됩니다. 의심되는 사람을 투표하세요. (10분 제한)\n\n"
            f"생존자 ({len(game.alive)}명): {alive_list}"
        ),
    )

    for player in game.alive:
        options = [
            {"text": {"type": "plain_text", "text": f"<@{p}>"}, "value": p}
            for p in game.alive
            if p != player
        ]
        options.append({"text": {"type": "plain_text", "text": "건너뛰기"}, "value": "skip"})

        send_dm(
            client,
            player,
            "투표 시간입니다. 처형할 사람을 선택하세요.",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": ":ballot_box: *투표 시간입니다.*\n처형할 사람을 선택하세요. (10분 제한)"},
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "static_select",
                            "placeholder": {"type": "plain_text", "text": "처형할 사람 선택"},
                            "options": options,
                            "action_id": "mafia_day_vote_select",
                        }
                    ],
                },
            ],
        )

    game.timer = threading.Timer(VOTE_TIMEOUT, day_timeout, args=[game, client])
    game.timer.daemon = True
    game.timer.start()


def day_timeout(game: Game, client):
    with game.lock:
        if game.phase != Phase.DAY:
            return
        not_voted = [p for p in game.alive if p not in game.day_votes]
        log_event(f"{C.YELLOW}시간 초과", f"낮 투표 10분 경과 (미투표: {names(not_voted, client)}){C.RESET}")
        post(game, client, ":hourglass: 투표 시간이 종료되었습니다! 현재 투표 결과로 집계합니다.")
        resolve_day(game, client)


def check_majority(game: Game, client) -> bool:
    vote_counts: dict[str, int] = {}
    for target in game.day_votes.values():
        if target == "skip":
            continue
        vote_counts[target] = vote_counts.get(target, 0) + 1

    majority = len(game.alive) // 2 + 1
    for target, count in vote_counts.items():
        if count >= majority:
            log_event(f"{C.MAGENTA}과반수!", f"{get_name(target, client)} {count}표 (과반 {majority}표){C.RESET}")
            cancel_timer(game)
            resolve_day(game, client)
            return True
    return False


def handle_day_vote(ack, body, client):
    ack()
    user = body["user"]["id"]
    selected = body["actions"][0]["selected_option"]["value"]

    game = None
    for g in sessions.values():
        if user in g.alive and g.phase == Phase.DAY:
            game = g
            break
    if not game:
        return

    with game.lock:
        if game.phase != Phase.DAY:
            return

        game.day_votes[user] = selected
        save(game)

        if selected == "skip":
            log_event(f"{C.YELLOW}낮 투표", f"{get_name(user, client)} → {C.DIM}건너뛰기{C.RESET}")
            send_dm(client, user, ":hand: 투표를 건너뛰었습니다.")
        else:
            log_event(f"{C.YELLOW}낮 투표", f"{get_name(user, client)} → {C.BOLD}{get_name(selected, client)}{C.RESET}")
            send_dm(client, user, f":ballot_box: <@{selected}>에게 투표했습니다.")

        voted = len(game.day_votes)
        total = len(game.alive)
        log_event(f"{C.DIM}진행", f"{voted}/{total} 투표 완료{C.RESET}")

        if check_majority(game, client):
            return

        if all(p in game.day_votes for p in game.alive):
            cancel_timer(game)
            resolve_day(game, client)


def resolve_day(game: Game, client):
    vote_counts: dict[str, int] = {}
    for target in game.day_votes.values():
        if target == "skip":
            continue
        vote_counts[target] = vote_counts.get(target, 0) + 1

    log_phase(f"{C.YELLOW}투표 결과{C.RESET}")
    for target, count in sorted(vote_counts.items(), key=lambda x: -x[1]):
        bar = "█" * count
        log_event(f"{C.YELLOW}{bar}", f"{get_name(target, client)}: {count}표{C.RESET}")
    skip_count = sum(1 for v in game.day_votes.values() if v == "skip")
    if skip_count:
        log_event(f"{C.DIM}{'█' * skip_count}", f"건너뛰기: {skip_count}표{C.RESET}")

    if not vote_counts:
        log_event(f"{C.DIM}결과", f"투표 없음 - 처형 없음{C.RESET}")
        post(game, client, ":no_entry_sign: 아무도 처형되지 않았습니다.")
        start_night(game, client)
        return

    max_votes = max(vote_counts.values())
    top_targets = [t for t, c in vote_counts.items() if c == max_votes]

    if len(top_targets) > 1:
        log_event(f"{C.DIM}결과", f"동률 - 처형 없음{C.RESET}")
        post(game, client, ":scales: 동률입니다! 아무도 처형되지 않았습니다.")
        start_night(game, client)
        return

    victim = top_targets[0]
    game.alive.remove(victim)
    save(game)

    role = "마피아" if victim in game.mafia else "시민"
    log_event(f"{C.MAGENTA}처형", f"{C.BOLD}{get_name(victim, client)}{C.RESET} ({role}) - 투표에 의해 처형됨")

    post(game, client, f":coffin: <@{victim}>님이 투표로 처형되었습니다. (정체: {role})")

    winner = check_win(game)
    if winner:
        end_game(game, winner, client)
        return

    start_night(game, client)


# ─── 게임 종료 ───


def end_game(game: Game, winner: str, client):
    cancel_timer(game)
    mafia_names = format_players(game.mafia)
    citizen_names = format_players(game.citizens)

    if winner == "mafia":
        log_header(f"{C.RED}게임 종료 - 마피아 승리!{C.RESET}")
    else:
        log_header(f"{C.GREEN}게임 종료 - 시민 승리!{C.RESET}")

    log_event(f"{C.RED}마피아", f"{names(game.mafia, client)}{C.RESET}")
    log_event(f"{C.GREEN}시  민", f"{names(game.citizens, client)}{C.RESET}")

    if winner == "mafia":
        text = f":smiling_imp: *마피아 승리!*\n\n마피아: {mafia_names}\n시민: {citizen_names}"
    else:
        text = f":tada: *시민 승리!*\n\n마피아: {mafia_names}\n시민: {citizen_names}"

    post(game, client, text)
    db.delete(game.channel)
    del sessions[game.channel]
