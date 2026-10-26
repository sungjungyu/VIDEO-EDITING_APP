"""Gemini 연결 확인 (예전 tests/test_gemini.py를 옮김).

    python scripts/check_gemini.py           모델 목록만 확인 (사용량 0)
    python scripts/check_gemini.py --call    짧은 JSON 요청 1회 (텍스트 모델 사용량 1회)

설정·모델 이름은 vibecut/settings.py 한 곳에서 읽는다.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibecut.ai.gemini import AIError, GeminiClient  # noqa: E402
from vibecut.settings import load_settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Gemini 연결 확인")
    ap.add_argument("--call", action="store_true", help="실제로 짧은 요청을 한 번 보낸다")
    args = ap.parse_args()
    settings = load_settings()
    if not settings.api_key:
        print("키가 없습니다. GEMINI_API_KEY 환경 변수 또는 gemini_key.txt를 확인하세요.")
        return 1
    from google import genai
    names = {m.name.replace("models/", "") for m in genai.Client(api_key=settings.api_key).models.list()}
    ok = True
    for role, name in settings.models.__dict__.items():
        found = name in names
        ok &= found
        print(f"{role:14s} {name:28s} {'있음' if found else '없음 — 환경 변수로 바꾸세요'}")
    if args.call:
        client = GeminiClient(settings)
        try:
            print("응답:", client.generate_json('{"ok": true}만 그대로 돌려줘.', purpose="연결 확인"))
        except AIError as error:
            print("요청 실패:", error)
            return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
