"""사다리타기 게임."""

from pathlib import Path

from db import GameDB
from utils import C, format_players, get_name, log_event, log_header, log_phase

from .game import LOSER_LABEL, Game, Phase, run_game

db = GameDB(str(Path(__file__).parent / "ladder.db"))

# channel_id -> Game
sessions: dict[str, Game] = {}


def save(game: Game):
    db.save(game.channel, game.to_dict())


def post(game: Game, client, text: str):
    client.chat_postMessage(channel=game.channel, thread_ts=game.thread_ts, text=text)


# ─── 핸들러 등록 ───


def register(app):
    app.action("ladder_join")(handle_join)
    app.action("ladder_start")(handle_start)


def restore(client):
    saved = db.load_all()
    for channel, data in saved.items():
        if data.get("game_type") != "ladder":
            continue
        game = Game.from_dict(data)
        if game.phase == Phase.LOBBY:
            sessions[channel] = game
            log_event(
                f"{C.CYAN}복원[사다리]",
                f"채널 {channel} / 참여자 {len(game.players)}명{C.RESET}",
            )


# ─── 슬래시 커맨드 ───


def new_game(ack, command, client):
    ack()
    channel = command["channel_id"]
    user = command["user_id"]

    if channel in sessions and sessions[channel].phase == Phase.LOBBY:
        client.chat_postEphemeral(
            channel=channel,
            user=user,
            text=":x: 이미 사다리타기 대기 중입니다. 참여하거나 시작해주세요.",
        )
        return

    game = Game(channel=channel, creator=user)
    sessions[channel] = game

    log_header(f"{C.YELLOW}새 사다리타기{C.RESET}{C.BOLD} by {get_name(user, client)}")

    result = client.chat_postMessage(
        channel=channel,
        text=f"<@{user}>님이 사다리타기를 열었습니다!",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"<@{user}>님이 *사다리타기* 를 열었습니다! :ladder:\n"
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
                        "action_id": "ladder_join",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "시작"},
                        "style": "danger",
                        "action_id": "ladder_start",
                    },
                ],
            },
        ],
    )
    game.thread_ts = result["ts"]
    save(game)


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
        text=f"사다리타기 참여자 모집 중! 현재 {len(game.players)}명",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*사다리타기* 참여자 모집 중! :ladder:\n"
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
                        "action_id": "ladder_join",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "시작"},
                        "style": "danger",
                        "action_id": "ladder_start",
                    },
                ],
            },
        ],
    )
    save(game)


# ─── 시작 ───


def handle_start(ack, body, client):
    ack()
    channel = body["channel"]["id"]
    user = body["user"]["id"]

    game = sessions.get(channel)
    if not game:
        client.chat_postEphemeral(
            channel=channel,
            user=user,
            text=":x: 열린 게임이 없습니다. `/새게임 사다리`로 먼저 게임을 만들어주세요.",
        )
        return
    if game.phase != Phase.LOBBY:
        client.chat_postEphemeral(channel=channel, user=user, text=":x: 이미 게임이 진행 중입니다.")
        return
    if game.creator != user:
        client.chat_postEphemeral(channel=channel, user=user, text=":x: 게임을 만든 사람만 시작할 수 있습니다.")
        return
    if len(game.players) < 2:
        client.chat_postEphemeral(channel=channel, user=user, text=":x: 최소 2명이 필요합니다.")
        return

    log_header(f"{C.GREEN}사다리타기 시작!{C.RESET}{C.BOLD} ({len(game.players)}명)")

    result, ladder_text = run_game(game.players)
    game.result = result
    game.phase = Phase.DONE
    save(game)

    # 참여하기/시작 버튼 제거
    player_list = format_players(game.players)
    client.chat_update(
        channel=channel,
        ts=game.thread_ts,
        text=f"사다리타기 완료! 참여자 {len(game.players)}명",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*사다리타기* 완료! :ladder:\n\n참여자 ({len(game.players)}명): {player_list}",
                },
            },
        ],
    )

    # 참여 번호 안내
    number_list = "\n".join(f"[{i + 1}] <@{p}>" for i, p in enumerate(game.players))
    log_phase(f"{C.YELLOW}사다리 결과{C.RESET}")

    post(
        game,
        client,
        f":ladder: *사다리타기 결과*\n\n참여자:\n{number_list}\n\n```\n{ladder_text}\n```",
    )

    # 결과 발표
    loser = next((p for p, label in result.items() if label == LOSER_LABEL), None)
    result_lines = []
    for i, player in enumerate(game.players):
        label = result[player]
        emoji = ":coffee:" if label == LOSER_LABEL else ":white_check_mark:"
        result_lines.append(f"{emoji} [{i + 1}] <@{player}>: {label}")
        log_event(
            f"{C.YELLOW}[{i + 1}]",
            f"{get_name(player, client)}: {label}{C.RESET}",
        )

    result_text = "\n".join(result_lines)

    if loser:
        post(
            game,
            client,
            f"*결과 발표!*\n\n{result_text}\n\n:coffee: <@{loser}>님이 *커피 당첨*되셨습니다! 모두에게 커피 한 잔씩 부탁드립니다 :pray:",
        )
        log_event(f"{C.RED}커피 당첨!", f"{get_name(loser, client)}{C.RESET}")
    else:
        post(game, client, f"*결과 발표!*\n\n{result_text}")

    db.delete(game.channel)
    del sessions[game.channel]
