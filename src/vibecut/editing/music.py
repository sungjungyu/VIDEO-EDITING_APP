"""배경음악 고르기: 장면 분석의 분위기(mood) 낱말 → 곡 분위기(잔잔·경쾌·감성) 추천."""

from __future__ import annotations

from collections import Counter

from ..domain.models import Scene

MOODS = ("잔잔", "경쾌", "감성")
_WORDS = {
    "경쾌": ("신나", "신남", "즐거", "활기", "유쾌", "밝", "설렘", "설레", "흥", "재미", "들뜬", "에너지", "웃"),
    "감성": ("감성", "감동", "그리", "노을", "쓸쓸", "아련", "몽환", "낭만", "로맨", "추억", "뭉클", "따뜻"),
    "잔잔": ("평화", "여유", "편안", "조용", "차분", "느긋", "잔잔", "고요", "한적", "포근"),
}


def scene_mood(text: str) -> str | None:
    for mood in ("경쾌", "감성", "잔잔"):
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
