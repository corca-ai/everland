"""공용 유틸리티 - 콘솔 로깅, 슬랙 헬퍼, 유저 이름 캐시."""


# ─── 콘솔 색상 ───


class C:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def log_header(text: str):
    print(f"\n{C.BOLD}{'═' * 50}{C.RESET}")
    print(f"{C.BOLD}  {text}{C.RESET}")
    print(f"{C.BOLD}{'═' * 50}{C.RESET}")


def log_event(icon: str, text: str):
    print(f"  {icon}  {text}")


def log_phase(text: str):
    print(f"\n{C.BOLD}{C.CYAN}── {text} ──{C.RESET}")


# ─── 유저 이름 캐시 ───

_name_cache: dict[str, str] = {}


def get_name(user_id: str, client) -> str:
    if user_id not in _name_cache:
        try:
            info = client.users_info(user=user_id)
            _name_cache[user_id] = info["user"]["real_name"] or info["user"]["name"]
        except Exception:
            _name_cache[user_id] = user_id
    return _name_cache[user_id]


def names(user_ids: list[str], client) -> str:
    return ", ".join(get_name(uid, client) for uid in user_ids)


# ─── 슬랙 헬퍼 ───


def format_players(user_ids: list[str]) -> str:
    return ", ".join(f"<@{uid}>" for uid in user_ids)


def send_dm(client, user_id: str, text: str, **kwargs):
    dm = client.conversations_open(users=[user_id])
    client.chat_postMessage(channel=dm["channel"]["id"], text=text, **kwargs)
