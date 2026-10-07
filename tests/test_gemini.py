#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini API 연결 테스트
"""

import google.generativeai as genai
from config import config

def test_gemini_api():
    """Gemini API 연결 테스트"""
    print("🔑 Gemini API 연결 테스트")
    print("=" * 40)
    
    # API 키 로드
    api_key = config.load_api_key()
    print(f"API 키 상태: {'✅ 로드됨' if api_key else '❌ 없음'}")
    
    if not api_key:
        print("❌ API 키를 먼저 설정해주세요.")
        return False
    
    try:
        # API 설정
        print("🔧 API 설정 중...")
        genai.configure(api_key=api_key)
        
        # 모델 생성
        print("🤖 모델 생성 중...")
        model = genai.GenerativeModel('gemini-3-flash')
        
        # 간단한 테스트
        print("📡 API 호출 테스트 중...")
        response = model.generate_content('Hello, please respond with "API working"')
        
        print(f"✅ API 연결 성공!")
        print(f"📝 응답: {response.text}")
        
        return True
        
    except Exception as e:
        print(f"❌ API 연결 실패: {e}")
        print("\n🔧 해결 방법:")
        print("1. API 키가 올바른지 확인")
        print("2. 인터넷 연결 확인")
        print("3. Google AI Studio에서 API 키 재발급")
        
        return False

if __name__ == "__main__":
    test_gemini_api()
