#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
설정 파일 - API 키 및 환경 변수 관리
"""

import os
from typing import Optional

class Config:
    """설정 관리 클래스"""
    
    def __init__(self):
        self.api_key_file = "gemini_key.txt"
    
    def load_api_key(self) -> Optional[str]:
        """
        API 키를 로드합니다 (우선순위: 환경변수 > 파일)
        
        Returns:
            Optional[str]: API 키 또는 None
        """
        # 1. 환경 변수 확인
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            print("✅ 환경 변수에서 API 키를 찾았습니다.")
            return api_key
        
        # 2. 파일 확인
        if os.path.exists(self.api_key_file):
            try:
                with open(self.api_key_file, 'r', encoding='utf-8') as f:
                    api_key = f.read().strip()
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
            print(f"✅ API 키를 '{self.api_key_file}' 파일에 저장했습니다.")
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
            
            # 자동으로 파일에 저장
            self.save_api_key(api_key)
            print("✅ 다음 실행부터 자동으로 API 키를 불러옵니다.")
            
            return api_key
            
        except KeyboardInterrupt:
            print("\n👋 설정을 취소했습니다.")
            return None

# 전역 설정 인스턴스
config = Config()
