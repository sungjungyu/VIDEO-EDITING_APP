#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini API 연결 확인 (실제 API를 1회 호출한다)

자동 테스트가 아니라 손으로 실행하는 확인용 스크립트다. 키 사용량이 나가므로
unittest/pytest가 자동으로 부르지 않게 함수 이름을 test_로 시작하지 않는다.

    python tests/test_gemini.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google import genai
from config import config

MODEL_NAME = "gemini-3.5-flash"   # main.py VideoEditingPipeline과 같은 모델


def check_gemini_api():
    """Gemini API 연결 확인"""
    print("🔑 Gemini API 연결 확인")
    print("=" * 40)

    # API 키 로드 (환경 변수 GEMINI_API_KEY → 프로젝트 폴더의 gemini_key.txt)
    api_key = config.load_api_key()
    print(f"API 키 상태: {'✅ 로드됨' if api_key else '❌ 없음'}")

    if not api_key:
        print("❌ API 키를 먼저 설정해주세요. (프로젝트 폴더에 gemini_key.txt 또는 환경 변수 GEMINI_API_KEY)")
        return False

    try:
        print(f"📡 API 호출 확인 중... ({MODEL_NAME})")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=MODEL_NAME, contents='Hello, please respond with "API working"')

        print("✅ API 연결 성공!")
        print(f"📝 응답: {response.text}")

        return True

    except Exception as e:
        print(f"❌ API 연결 실패: {e}")
        print("\n🔧 해결 방법:")
        print("1. API 키가 올바른지 확인")
        print("2. 인터넷 연결 확인")
        print("3. Google AI Studio에서 API 키 재발급")
        print("4. 429(사용 한도 초과)면 한도가 다시 찰 때까지 기다리기 (무료 키는 하루 한도가 있음)")

        return False


if __name__ == "__main__":
    sys.exit(0 if check_gemini_api() else 1)
