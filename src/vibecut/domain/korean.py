"""한국어 말 규칙 사전: 촬영 지시어·추임새·강조 단어와 글자 비교 도구.

컷 판단(analysis.judge)·렌더 전 검사(editing.planner)·받아쓰기 환각 판별(analysis.stt)이 함께 쓴다.
"""

from __future__ import annotations

import re

# "다시 할게", "처음부터"처럼 촬영 중에 한 지시·NG 신호
CUE_PATTERN = re.compile(r"(다시\s*(할게|갈게|찍|해)|처음부터|컷\s*컷|편집\s*해|자를게|잘라\s*줘|엔지|NG|잠깐만)")

FILLERS = {"음", "어", "아", "에", "흠", "으", "엄", "저", "그", "음음", "어어", "아아", "그니까", "그러니까", "뭐지",
           "뭐랄까", "약간", "이제", "막", "뭐", "근데"}
REPEATED_FILLER = re.compile(r"^(음|어|아|으|흠|에|엄)\1*$")
EMPHASIS_WORDS = ("대박", "진짜", "완전", "최고", "헐", "미쳤", "레전드", "꿀팁", "핵심", "중요", "와!")

_PUNCT = re.compile(r"[\s.,!?…~\-\"'·]+")
_NON_WORD = re.compile(r"[\W_]+")


def normalize(text: str) -> str:
    """공백·문장부호를 뺀 글자만."""
    return _PUNCT.sub("", text)


def tokens(text: str) -> list[str]:
    """공백으로 나눈 낱말 (문장부호 제거, 빈 낱말 제외)."""
    return [t for t in (_PUNCT.sub("", tok) for tok in text.split()) if t]


def letters_only(text: str) -> str:
    """글자·숫자만 (밑줄 포함 기호 전부 제거)."""
    return _NON_WORD.sub("", text)


def bigram_overlap(a: str, b: str) -> float:
    """a의 글자 2개 묶음 중 b에도 있는 비율 (0~1)."""
    grams = [a[i:i + 2] for i in range(len(a) - 1)]
    if not grams:
        return 0.0
    ref = {b[i:i + 2] for i in range(len(b) - 1)}
    return sum(g in ref for g in grams) / len(grams)
