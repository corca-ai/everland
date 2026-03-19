"""마피아 게임."""

import random
import threading
from pathlib import Path

from slack_sdk.errors import SlackApiError

from db import GameDB
from utils import C, format_players, get_name, log_event, log_header, log_phase, names, send_dm

from .game import (
    VOTE_TIMEOUT,
    Game,
    Phase,
    check_win,
    has_majority,
    mafia_count,
    night_all_done,
    resolve_day_votes,
    resolve_night_votes,
    role_name,
    special_count,
)
from .game import (
    assign_roles as assign_roles,
)

db = GameDB(str(Path(__file__).parent / "mafia.db"))

# channel_id -> Game
sessions: dict[str, Game] = {}


def save(game: Game):
    db.save(game.channel, game.to_dict())


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
    app.action("mafia_join_game")(handle_join)
    app.action("mafia_start_game")(handle_start_game)
    app.action("mafia_kill_select")(handle_mafia_vote)
    app.action("mafia_doctor_select")(handle_doctor_vote)
    app.action("mafia_police_select")(handle_police_vote)
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
                        f"<@{user}>님이 *마피아 게임*을 열었습니다! {random.choice([':female-detective:', ':male-detective:'])}\n"
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
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "시작"},
                        "style": "danger",
                        "action_id": "mafia_start_game",
                    },
                ],
            },
        ],
    )
    game.thread_ts = result["ts"]
    save(game)


def handle_start_game(ack, body, client):
    ack()
    channel = body["channel"]["id"]
    user = body["user"]["id"]

    game = sessions.get(channel)
    if not game:
        client.chat_postEphemeral(
            channel=channel, user=user, text=":x: 열린 게임이 없습니다. `/새게임`으로 먼저 게임을 만들어주세요."
        )
        return
    if game.phase != Phase.LOBBY:
        client.chat_postEphemeral(channel=channel, user=user, text=":x: 이미 게임이 진행 중입니다.")
        return
    if game.creator != user:
        client.chat_postEphemeral(channel=channel, user=user, text=":x: 게임을 만든 사람만 시작할 수 있습니다.")
        return
    if len(game.players) < 4:
        client.chat_postEphemeral(channel=channel, user=user, text=":x: 최소 4명이 필요합니다.")
        return

    n_mafia = mafia_count(len(game.players))
    n_doc, n_cop = special_count(len(game.players))
    shuffled = game.players[:]
    random.shuffle(shuffled)
    game.mafia = shuffled[:n_mafia]
    game.citizens = shuffled[n_mafia:]
    game.alive = game.players[:]
    game.doctors = game.citizens[:n_doc]
    game.polices = game.citizens[n_doc : n_doc + n_cop]

    mafia_names_str = format_players(game.mafia)

    log_header(f"{C.GREEN}게임 시작!{C.RESET}{C.BOLD} ({len(game.players)}명)")
    log_event(f"{C.RED}마피아", f"{names(game.mafia, client)}{C.RESET}")
    if game.doctors:
        log_event(f"{C.CYAN}의  사", f"{names(game.doctors, client)}{C.RESET}")
    if game.polices:
        log_event(f"{C.MAGENTA}경  찰", f"{names(game.polices, client)}{C.RESET}")
    log_event(f"{C.GREEN}시  민", f"{names(game.citizens, client)}{C.RESET}")

    for player in game.players:
        if player in game.mafia:
            send_dm(client, player, f":smiling_imp: 당신은 *마피아*입니다!\n동료 마피아: {mafia_names_str}")
        elif player in game.doctors:
            send_dm(
                client,
                player,
                ":hospital: 당신은 *의사*입니다.\n매 밤 한 명을 선택해 보호할 수 있습니다. 마피아가 그 사람을 공격하면 살릴 수 있습니다.",
            )
        elif player in game.polices:
            send_dm(
                client,
                player,
                ":police_officer: 당신은 *경찰*입니다.\n매 밤 한 명을 조사해 마피아인지 알아낼 수 있습니다.",
            )
        else:
            send_dm(client, player, ":innocent: 당신은 *시민*입니다.\n마피아를 찾아내세요!")

    # 로비 메시지에서 참여하기 버튼 제거
    player_list = format_players(game.players)
    try:
        client.chat_update(
            channel=channel,
            ts=game.thread_ts,
            text=f"마피아 게임 시작! 참여자 {len(game.players)}명",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*마피아 게임* 이 시작되었습니다! :game_die:\n\n참여자 ({len(game.players)}명): {player_list}"
                        ),
                    },
                },
            ],
        )
    except SlackApiError as e:
        if e.response.get("error") != "message_not_found":
            raise
        log_event(f"{C.RED}오류", f"로비 메시지가 삭제됨 — 계속 진행 (채널 {channel}){C.RESET}")

    n_plain = len(game.citizens) - n_doc - n_cop
    role_text = f":game_die: 게임이 시작됩니다! 참여자 {len(game.players)}명, 마피아 {n_mafia}명"
    if n_doc:
        role_text += f", 의사 {n_doc}명"
    if n_cop:
        role_text += f", 경찰 {n_cop}명"
    role_text += f", 시민 {n_plain}명"
    role_text += "\n역할이 DM으로 전달되었습니다."
    post(game, client, role_text)

    start_day(game, client)


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

    try:
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
                            f"*마피아 게임* 참여자 모집 중! {random.choice([':female-detective:', ':male-detective:'])}\n"
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
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "시작"},
                            "style": "danger",
                            "action_id": "mafia_start_game",
                        },
                    ],
                },
            ],
        )
    except SlackApiError as e:
        if e.response.get("error") == "message_not_found":
            log_event(f"{C.RED}오류", f"로비 메시지가 삭제됨 — 세션 정리 (채널 {channel}){C.RESET}")
            db.delete(channel)
            del sessions[channel]
            client.chat_postEphemeral(
                channel=channel,
                user=user,
                text=":x: 게임 로비 메시지가 삭제되었습니다. `/새게임 마피아`로 다시 시작해주세요.",
            )
            return
        raise
    save(game)


# ─── 밤 ───


def start_night(game: Game, client):
    game.phase = Phase.NIGHT
    game.night_votes = {}
    game.doctor_targets = {}
    game.police_targets = {}
    save(game)

    log_phase(f"{C.BLUE}밤이 되었습니다{C.RESET}")
    log_status(game, client)

    alive_mafia = [m for m in game.mafia if m in game.alive]
    log_event(f"{C.RED}마피아 투표 대기 중...", f"{names(alive_mafia, client)}{C.RESET}")

    post(
        game,
        client,
        ":night_with_stars: *밤이 되었습니다.* 마피아가 활동합니다...\n:shushing_face: *스레드에서 대화하지 마세요!* 모두 잠드세요. (5분 제한)",
    )

    # 마피아 DM
    kill_options = [
        {"text": {"type": "plain_text", "text": f"<@{p}>"}, "value": p} for p in game.alive if p not in game.mafia
    ]
    mafia_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":night_with_stars: *밤이 되었습니다.*\n죽일 사람을 선택하세요. (5분 제한)",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "static_select",
                    "placeholder": {"type": "plain_text", "text": "대상 선택"},
                    "options": kill_options,
                    "action_id": "mafia_kill_select",
                }
            ],
        },
    ]
    for m in alive_mafia:
        send_dm(client, m, "밤입니다. 죽일 사람을 선택하세요.", blocks=mafia_blocks)

    # 의사 DM
    doc_options = [{"text": {"type": "plain_text", "text": f"<@{p}>"}, "value": p} for p in game.alive]
    doc_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":hospital: *밤이 되었습니다.*\n보호할 사람을 선택하세요. 선택한 사람이 마피아에게 공격당하면 살릴 수 있습니다. (5분 제한)",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "static_select",
                    "placeholder": {"type": "plain_text", "text": "보호할 사람 선택"},
                    "options": doc_options,
                    "action_id": "mafia_doctor_select",
                }
            ],
        },
    ]
    for d in game.doctors:
        if d in game.alive:
            send_dm(client, d, "밤입니다. 보호할 사람을 선택하세요.", blocks=doc_blocks)

    # 경찰 DM
    for c in game.polices:
        if c in game.alive:
            cop_options = [
                {"text": {"type": "plain_text", "text": f"<@{p}>"}, "value": p} for p in game.alive if p != c
            ]
            cop_blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":police_officer: *밤이 되었습니다.*\n조사할 사람을 선택하세요. 선택한 사람이 마피아인지 알려드립니다. (5분 제한)",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "static_select",
                            "placeholder": {"type": "plain_text", "text": "조사할 사람 선택"},
                            "options": cop_options,
                            "action_id": "mafia_police_select",
                        }
                    ],
                },
            ]
            send_dm(client, c, "밤입니다. 조사할 사람을 선택하세요.", blocks=cop_blocks)

    game.timer = threading.Timer(VOTE_TIMEOUT, night_timeout, args=[game, client])
    game.timer.daemon = True
    game.timer.start()


def night_timeout(game: Game, client):
    with game.lock:
        if game.phase != Phase.NIGHT:
            return
        log_event(f"{C.RED}시간 초과", f"밤 투표 5분 경과{C.RESET}")
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

        if night_all_done(game):
            cancel_timer(game)
            resolve_night(game, client)


def handle_doctor_vote(ack, body, client):
    ack()
    user = body["user"]["id"]
    selected = body["actions"][0]["selected_option"]["value"]

    game = None
    for g in sessions.values():
        if user in g.doctors and g.phase == Phase.NIGHT:
            game = g
            break
    if not game:
        return

    with game.lock:
        if game.phase != Phase.NIGHT:
            return

        game.doctor_targets[user] = selected
        save(game)

        log_event(
            f"{C.CYAN}의사 보호",
            f"{get_name(user, client)} → {C.BOLD}{get_name(selected, client)}{C.RESET}",
        )

        send_dm(client, user, f":hospital: <@{selected}>을(를) 보호합니다.")

        if night_all_done(game):
            cancel_timer(game)
            resolve_night(game, client)


def handle_police_vote(ack, body, client):
    ack()
    user = body["user"]["id"]
    selected = body["actions"][0]["selected_option"]["value"]

    game = None
    for g in sessions.values():
        if user in g.polices and g.phase == Phase.NIGHT:
            game = g
            break
    if not game:
        return

    with game.lock:
        if game.phase != Phase.NIGHT:
            return

        game.police_targets[user] = selected
        save(game)

        is_mafia = selected in game.mafia
        result = "마피아" if is_mafia else "마피아가 아닙니다"
        emoji = ":rotating_light:" if is_mafia else ":white_check_mark:"

        log_event(
            f"{C.MAGENTA}경찰 조사",
            f"{get_name(user, client)} → {C.BOLD}{get_name(selected, client)}{C.RESET} ({'마피아' if is_mafia else '시민'})",
        )

        send_dm(client, user, f"{emoji} <@{selected}>의 조사 결과: *{result}*")

        if night_all_done(game):
            cancel_timer(game)
            resolve_night(game, client)


def resolve_night(game: Game, client):
    victim, protected = resolve_night_votes(game)

    if victim is None:
        log_event(f"{C.DIM}결과", f"투표 없음 - 아무도 죽지 않음{C.RESET}")
        post(game, client, ":sunrise: *아침이 밝았습니다.*\n간밤에는 아무 일도 일어나지 않았습니다.")
        start_day(game, client)
        return

    if protected:
        log_phase(f"{C.YELLOW}아침이 밝았습니다{C.RESET}")
        log_event(f"{C.CYAN}의사 보호 성공!", f"{C.BOLD}{get_name(victim, client)}{C.RESET} - 의사가 살림")
        post(
            game,
            client,
            ":sunrise: *아침이 밝았습니다.*\n\n:hospital: 누군가 마피아에게 습격당했지만, 의사의 활약으로 살아남았습니다!",
        )

        winner = check_win(game)
        if winner:
            end_game(game, winner, client)
            return

        start_day(game, client)
        return

    game.alive.remove(victim)
    save(game)

    is_mafia = victim in game.mafia
    reveal = "마피아" if is_mafia else "마피아가 아닙니다"

    log_phase(f"{C.YELLOW}아침이 밝았습니다{C.RESET}")
    log_event(
        f"{C.RED}사망",
        f"{C.BOLD}{get_name(victim, client)}{C.RESET} ({role_name(game, victim)}) - 마피아에 의해 살해됨",
    )

    post(
        game,
        client,
        f":sunrise: *아침이 밝았습니다.*\n\n:skull: <@{victim}>님이 마피아에 의해 살해당했습니다. ({reveal})",
    )

    winner = check_win(game)
    if winner:
        end_game(game, winner, client)
        return

    start_day(game, client)


# ─── 낮 ───


def start_day(game: Game, client):
    game.phase = Phase.DAY
    game.day_votes = {}
    game.runoff_targets = []
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
            f"DM으로 투표가 전송됩니다. 의심되는 사람을 투표하세요. (5분 제한)\n\n"
            f"생존자 ({len(game.alive)}명): {alive_list}"
        ),
    )

    for player in game.alive:
        options = [{"text": {"type": "plain_text", "text": f"<@{p}>"}, "value": p} for p in game.alive if p != player]
        options.append({"text": {"type": "plain_text", "text": "건너뛰기"}, "value": "skip"})

        send_dm(
            client,
            player,
            "투표 시간입니다. 처형할 사람을 선택하세요.",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":ballot_box: *투표 시간입니다.*\n처형할 사람을 선택하세요. (5분 제한)",
                    },
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
        log_event(f"{C.YELLOW}시간 초과", f"낮 투표 5분 경과 (미투표: {names(not_voted, client)}){C.RESET}")
        post(game, client, ":hourglass: 투표 시간이 종료되었습니다! 현재 투표 결과로 집계합니다.")
        resolve_day(game, client)


def check_majority(game: Game, client) -> bool:
    target = has_majority(game)
    if target:
        log_event(f"{C.MAGENTA}과반수!", f"{get_name(target, client)} (과반 {len(game.alive) // 2 + 1}표){C.RESET}")
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


def start_runoff(game: Game, targets: list[str], client):
    game.day_votes = {}
    game.runoff_targets = targets
    save(game)

    target_names = format_players(targets)

    log_phase(f"{C.YELLOW}결선 투표{C.RESET}")
    log_event(f"{C.YELLOW}후보", f"{names(targets, client)}{C.RESET}")

    post(
        game,
        client,
        (
            f":scales: *동률입니다!* 결선 투표를 진행합니다.\n"
            f"후보: {target_names}\n"
            f"DM으로 결선 투표가 전송됩니다. (5분 제한)"
        ),
    )

    for player in game.alive:
        candidates = [t for t in targets if t != player]
        if not candidates:
            continue
        options = [{"text": {"type": "plain_text", "text": f"<@{p}>"}, "value": p} for p in candidates]
        options.append({"text": {"type": "plain_text", "text": "건너뛰기"}, "value": "skip"})

        send_dm(
            client,
            player,
            "결선 투표입니다.",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":scales: *결선 투표입니다.*\n동률인 후보 중 처형할 사람을 선택하세요. (5분 제한)",
                    },
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


def resolve_day(game: Game, client):
    result = resolve_day_votes(game)

    # 로깅
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

    if result is None:
        log_event(f"{C.DIM}결과", f"투표 없음 - 처형 없음{C.RESET}")
        post(game, client, ":no_entry_sign: 아무도 처형되지 않았습니다.")
        start_night(game, client)
        return

    if isinstance(result, list):
        # 동률
        if game.runoff_targets:
            log_event(f"{C.DIM}결과", f"결선 동률 - 처형 없음{C.RESET}")
            post(game, client, ":scales: 결선 투표에서도 동률입니다! 아무도 처형되지 않았습니다.")
            start_night(game, client)
            return
        log_event(f"{C.YELLOW}동률!", f"{names(result, client)} → 결선 투표{C.RESET}")
        start_runoff(game, result, client)
        return

    victim = result
    game.alive.remove(victim)
    save(game)

    is_mafia = victim in game.mafia
    reveal = "마피아" if is_mafia else "마피아가 아닙니다"
    log_event(
        f"{C.MAGENTA}처형",
        f"{C.BOLD}{get_name(victim, client)}{C.RESET} ({role_name(game, victim)}) - 투표에 의해 처형됨",
    )

    post(game, client, f":coffin: <@{victim}>님이 투표로 처형되었습니다. ({reveal})")

    winner = check_win(game)
    if winner:
        end_game(game, winner, client)
        return

    start_night(game, client)


# ─── 게임 종료 ───


def end_game(game: Game, winner: str, client):
    cancel_timer(game)
    mafia_names = format_players(game.mafia)

    if winner == "mafia":
        log_header(f"{C.RED}게임 종료 - 마피아 승리!{C.RESET}")
    else:
        log_header(f"{C.GREEN}게임 종료 - 시민 승리!{C.RESET}")

    log_event(f"{C.RED}마피아", f"{names(game.mafia, client)}{C.RESET}")
    if game.doctors:
        log_event(f"{C.CYAN}의  사", f"{names(game.doctors, client)}{C.RESET}")
    if game.polices:
        log_event(f"{C.MAGENTA}경  찰", f"{names(game.polices, client)}{C.RESET}")
    log_event(f"{C.GREEN}시  민", f"{names(game.citizens, client)}{C.RESET}")

    role_lines = [f"마피아: {mafia_names}"]
    if game.doctors:
        role_lines.append(f"의사: {format_players(game.doctors)}")
    if game.polices:
        role_lines.append(f"경찰: {format_players(game.polices)}")
    specials = set(game.doctors + game.polices)
    plain_citizens = [p for p in game.citizens if p not in specials]
    if plain_citizens:
        role_lines.append(f"시민: {format_players(plain_citizens)}")
    roles_text = "\n".join(role_lines)

    if winner == "mafia":
        text = f":smiling_imp: *마피아 승리!*\n\n{roles_text}"
    else:
        text = f":tada: *시민 승리!*\n\n{roles_text}"

    post(game, client, text)
    db.delete(game.channel)
    del sessions[game.channel]
