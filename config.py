#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
설정 파일 - API 키 및 환경 변수 관리
"""

import os
import sys
from pathlib import Path
from typing import Optional

# 진행 로그의 이모지(✅ 🧠 ⚠️ …)가 한글 윈도우(cp949) 출력에서 UnicodeEncodeError를 내지 않게 한다.
# (Git Bash·출력 저장(>)·일부 IDE 실행 창. app.py와 같은 처리, config를 불러오는 모든 모듈에 적용됨)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

class Config:
    """설정 관리 클래스"""
    
    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent
        self.api_key_file = self.base_dir / "gemini_key.txt"
    
    def load_api_key(self) -> Optional[str]:
        """
        API 키를 로드합니다 (우선순위: 환경변수 > 파일)
        
        Returns:
            Optional[str]: API 키 또는 None
        """
        # 1. 환경 변수 확인
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            api_key = api_key.replace("\ufeff", "").strip().strip('"').strip("'")
            print("✅ 환경 변수에서 API 키를 찾았습니다.")
            return api_key
        
        # 2. 파일 확인
        if self.api_key_file.exists():
            try:
                with open(self.api_key_file, 'r', encoding='utf-8') as f:
                    api_key = f.read().replace("\ufeff", "").strip().strip('"').strip("'")
                if api_key:
                    print("✅ 파일에서 API 키를 찾았습니다.")
                    return api_key
            except Exception as e:
                print(f"❌ API 키 파일 읽기 오류: {e}")
        
        return None
    
    def save_api_key(self, api_key: str) -> bool:
        """
        API 키를 파일에 저장합니다
        
        Args:
            api_key (str): 저장할 API 키
            
        Returns:
            bool: 저장 성공 여부
        """
        try:
            with open(self.api_key_file, 'w', encoding='utf-8') as f:
                f.write(api_key.strip())
            print(f"✅ API 키를 '{self.api_key_file.name}' 파일에 저장했습니다.")
            return True
        except Exception as e:
            print(f"❌ API 키 저장 오류: {e}")
            return False
    
    def setup_api_key(self) -> Optional[str]:
        """
        API 키를 설정합니다 (대화형)
        
        Returns:
            Optional[str]: 설정된 API 키 또는 None
        """
        try:
            api_key = input("Gemini API 키: ").strip()
            if not api_key:
                print("❌ API 키가 입력되지 않았습니다.")
                return None

            api_key = api_key.replace("\ufeff", "").strip().strip('"').strip("'")
            
            # 자동으로 파일에 저장
            self.save_api_key(api_key)
            print("✅ 다음 실행부터 자동으로 API 키를 불러옵니다.")
            
            return api_key
            
        except KeyboardInterrupt:
            print("\n👋 설정을 취소했습니다.")
            return None

# 전역 설정 인스턴스
config = Config()
