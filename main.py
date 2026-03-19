import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv()

from games import ladder, mafia
from utils import C, log_header, log_phase

app = App(token=os.environ["SLACK_BOT_TOKEN"])

# 게임 등록 — 새 게임을 추가하려면 여기에 import하고 register/restore 호출
# 슬래시 커맨드는 새로 추가하지 않고 /새게임 [게임명] 형식을 사용한다
mafia.register(app)
ladder.register(app)


@app.command("/시작")
def handle_slash_start(ack, command, client):
    ack()
    client.chat_postEphemeral(
        channel=command["channel_id"],
        user=command["user_id"],
        text=":information_source: `/시작` 커맨드는 지원하지 않습니다.\n게임 로비 메시지의 *시작* 버튼을 눌러주세요.",
    )


@app.command("/새게임")
def route_new_game(ack, command, client):
    text = command.get("text", "").strip()
    if text == "사다리":
        ladder.new_game(ack, command, client)
    elif text in ("", "마피아"):
        mafia.new_game(ack, command, client)
    else:
        ack()
        client.chat_postMessage(
            channel=command["channel_id"],
            text=(
                f":x: 알 수 없는 게임 종류입니다: `{text}`\n"
                "사용 가능한 게임: `마피아`, `사다리`\n"
                "예) `/새게임 마피아` 또는 `/새게임 사다리`"
            ),
        )


if __name__ == "__main__":
    import signal

    import jurigged

    watcher = jurigged.watch(autostart=False)

    def _reload(signum, frame):
        log_phase(f"{C.YELLOW}코드 리로드{C.RESET}")
        for path, cf in watcher.registry.cache.items():
            cf.refresh()

    signal.signal(signal.SIGUSR1, _reload)

    log_header(f"{C.GREEN}환상의나라 시작{C.RESET}")

    log_phase(f"{C.CYAN}저장된 게임 복원{C.RESET}")
    mafia.restore(app.client)
    ladder.restore(app.client)

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
