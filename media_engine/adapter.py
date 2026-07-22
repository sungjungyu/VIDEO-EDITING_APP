"""
AI 팀(팀원3) 세그먼트 포맷 → render_video() edit_data 포맷 변환 어댑터

AI 팀 SubtitleSegment:
    { start, end, text, cut: bool, subtitle_color, fontsize }
    cut=True  → 삭제할 구간
    cut=False → 유지할 구간

우리 edit_data:
    {
        "cuts": [{"start", "end"}, ...],   # 유지할 구간
        "subtitles": [{"start", "end", "text"}, ...],
        "style_preset": str,
    }
"""


def segments_to_edit_data(
    segments: list[dict],
    style_preset: str = "정석맛",
) -> dict:
    """
    segments: AI 팀 SubtitleSegment 딕셔너리 리스트
    style_preset: "매운맛" | "순한맛" | "정석맛"

    반환: render_video()에 바로 넘길 수 있는 edit_data dict
    """
    kept = [s for s in segments if not s.get("cut", False)]

    cuts = [{"start": s["start"], "end": s["end"]} for s in kept]

    subtitles = [
        {"start": s["start"], "end": s["end"], "text": s["text"]}
        for s in kept
        if s.get("text", "").strip()
    ]

    return {
        "cuts": cuts,
        "subtitles": subtitles,
        "style_preset": style_preset,
    }
