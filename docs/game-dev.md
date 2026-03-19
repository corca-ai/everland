# 게임 개발 가이드

## 게임 구조

각 게임은 `games/` 아래 독립된 패키지(디렉토리)로 존재한다.

```
games/
  새게임/
    __init__.py   # register(app), restore(client) 함수 제공
    ...           # 게임 내부 모듈, DB 파일 등
```

## 게임 추가 절차

1. `games/새게임/` 패키지 생성
2. `__init__.py`에 `register(app)`, `restore(client)` 함수 작성
3. `main.py`에서 import 후 `register(app)`, `restore(client)` 호출

## 데이터 저장

각 게임은 자체 SQLite DB를 패키지 디렉토리 안에 둔다.

```python
from pathlib import Path
from db import GameDB

db = GameDB(str(Path(__file__).parent / "새게임.db"))
```

`db.save(channel, data)`, `db.load_all()`, `db.delete(channel)`로 조작.

## 규칙

- 게임 진행 중 서버가 재시작되어도 게임이 이어져야 함
- 게임 진행 메시지는 스레드(댓글)로 전송
- 액션 ID는 게임별 접두사 사용 (예: `mafia_kill_select`)
- 게임 간 의존성 없이 독립적으로 동작해야 함

## 슬래시 커맨드 규칙

**새 슬래시 커맨드를 추가하지 않는다.** 모든 게임은 `/새게임 [게임명]` 형식으로 시작한다.

- `/새게임 마피아` → 마피아 게임 시작
- `/새게임 사다리` → 사다리타기 게임 시작

새 게임을 추가할 때는 `main.py`의 `route_new_game` 함수에 분기만 추가하면 된다. 게임 모듈에서 `app.command()`를 직접 호출하지 않는다.
