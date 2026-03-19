import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv()

from games import mafia
from utils import C, log_header, log_phase

app = App(token=os.environ["SLACK_BOT_TOKEN"])

# 게임 등록 — 새 게임을 추가하려면 여기에 import하고 register/restore 호출
mafia.register(app)


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

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
