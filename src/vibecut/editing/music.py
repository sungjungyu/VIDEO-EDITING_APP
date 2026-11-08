"""배경음악 고르기: 장면 분석의 분위기(mood) 낱말 → 곡 분위기(잔잔·경쾌·감성·웃김) 추천."""

from __future__ import annotations

from collections import Counter

from ..domain.models import Scene

MOODS = ("잔잔", "경쾌", "감성", "웃김")
_WORDS = {
    "웃김": ("웃", "재미", "유쾌", "코믹", "황당", "장난", "엉뚱", "익살", "개그", "폭소", "당황", "어이없"),   # 예능
    "경쾌": ("신나", "신남", "즐거", "활기", "밝", "설렘", "설레", "흥", "들뜬", "에너지"),
    "감성": ("감성", "감동", "그리", "노을", "쓸쓸", "아련", "몽환", "낭만", "로맨", "추억", "뭉클", "따뜻"),
    "잔잔": ("평화", "여유", "편안", "조용", "차분", "느긋", "잔잔", "고요", "한적", "포근"),
}


def scene_mood(text: str) -> str | None:
    for mood in ("웃김", "경쾌", "감성", "잔잔"):              # 더 구체적인 분위기부터
        if any(w in text for w in _WORDS[mood]):
            return mood
    return None


def recommend_mood(scenes: list[Scene]) -> str:
    """장면 길이로 가중한 가장 많은 분위기. 모르면 잔잔."""
    votes: Counter = Counter()
    for sc in scenes:
        mood = scene_mood(" ".join([sc.mood, sc.summary, sc.event]))
        if mood:
            votes[mood] += max(0.0, sc.end - sc.start)
    return votes.most_common(1)[0][0] if votes else "잔잔"
