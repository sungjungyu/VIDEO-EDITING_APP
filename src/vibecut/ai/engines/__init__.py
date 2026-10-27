"""받아쓰기·장면 분석 엔진 (팀원이 만든 원본 엔진, 단독 CLI 포함).

    transcriber     받아쓰기 (Whisper 로컬 / Gemini) + 무음 기준 단어 경계 보정   — 권용관
    scene_analyzer  Gemini 영상 이해로 장면 목록 만들기                          — 조경우

앱은 이 모듈을 직접 부르지 않고 vibecut.ai.stt / scenes를 거친다 (엔진 선택·대체·캐시).
단독 실행: python -m vibecut.ai.engines.transcriber --help
"""
