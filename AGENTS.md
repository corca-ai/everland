# 환상의나라(everland) 에이전트 가이드

슬랙 기반 멀티 게임 봇 프로젝트.

## 프로젝트 구조

```
main.py          # 앱 진입점 — 게임 모듈 등록
db.py            # SQLite 저장소 (channel → JSON)
utils.py         # 공용 유틸 (콘솔 로깅, 슬랙 헬퍼, 유저 이름 캐시)
games/
  mafia.py       # 마피아 게임
```

## 기술 스택

- Python 3.14, uv
- slack-bolt (Socket Mode)
- SQLite (표준 라이브러리)

## 실행

```bash
cp .env.example .env  # SLACK_BOT_TOKEN, SLACK_APP_TOKEN 설정
uv run main.py
```

## 새 게임 추가 방법

1. `games/새게임.py` 작성
2. `register(app)` 함수에서 슬래시 커맨드와 액션 핸들러 등록
3. `restore(client)` 함수에서 서버 재시작 시 DB 복원 처리
4. `main.py`에서 import 후 `register(app)`, `restore(client)` 호출

각 게임은 독립적. 공유하는 건 `db.py`와 `utils.py`뿐.

## 주요 규칙

- 게임 진행 메시지는 스레드(댓글)로 전송
- 투표는 DM으로 진행, 10분 제한
- 낮 투표 과반수 시 즉시 처형
- 액션 ID는 게임별 접두사 사용 (예: `mafia_kill_select`)

## 상세 문서

- [문서 작성 가이드](docs/metadoc.md)
