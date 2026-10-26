#!/usr/bin/env python3
"""VIBE CUT 웹 서버.

    python app.py            → http://127.0.0.1:8000
    uvicorn app:app --reload (개발용)

설정(주소·AI 모드·모델 이름·데이터 폴더)은 환경 변수로 바꾼다: vibecut/settings.py 참고.
"""

import uvicorn

from vibecut.server.app import create_app
from vibecut.settings import get_settings

app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    print(f"VIBE CUT 서버 시작: http://{settings.host}:{settings.port}")
    uvicorn.run(app, host=settings.host, port=settings.port)
