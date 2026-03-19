# 환상의나라(everland) 에이전트 가이드

슬랙 기반 멀티 게임 봇 프로젝트.

## 프로젝트 구조

```
main.py          # 앱 진입점 — 게임 모듈 등록
db.py            # GameDB 클래스
utils.py         # 공용 유틸 (콘솔 로깅, 슬랙 헬퍼, 유저 이름 캐시)
games/
  mafia/         # 마피아 게임 (패키지)
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

코드 수정 후 `kill -USR1 $(pgrep -f main.py)`로 리로드 (jurigged, 재시작 불필요).

## 주요 규칙

- 게임 진행 중 서버가 재시작되어도 게임이 이어져야 함
- 게임 진행 메시지는 스레드(댓글)로 전송
- 각 게임은 독립적으로 동작해야 함

## 상세 문서

- [게임 개발 가이드](docs/game-dev.md)
- [문서 작성 가이드](docs/metadoc.md)
