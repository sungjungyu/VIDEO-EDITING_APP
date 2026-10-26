from . import config

# 팀원3(AI 파이프라인)의 스타일 분석 출력값과 이름이 일치해야 함
PRESETS: dict[str, dict] = {
    "매운맛": {
        "font_name": config.DEFAULT_FONT,
        "font_size": 28,
        "primary_colour": "&H0000FFFF",   # 노란색 (ASS BGR 16진수)
        "secondary_colour": "&H000000FF",  # 빨간색 (카라오케 하이라이트)
        "outline_colour": "&H00000000",    # 검정 외곽선
        "back_colour": "&H80000000",       # 반투명 검정 배경
        "bold": 1,
        "italic": 0,
        "border_style": 3,                 # 불투명 배경 박스
        "outline": 2,
        "shadow": 1,
        "alignment": 2,                    # 하단 중앙
        "margin_v": 30,
        "fade_in": 150,
        "fade_out": 150,
    },
    "순한맛": {
        "font_name": config.DEFAULT_FONT,
        "font_size": 22,
        "primary_colour": "&H00FFFFFF",    # 흰색
        "secondary_colour": "&H0000FFFF",  # 노란색 (카라오케 하이라이트)
        "outline_colour": "&H00000000",    # 검정 외곽선
        "back_colour": "&H00000000",
        "bold": 0,
        "italic": 0,
        "border_style": 1,                 # 외곽선+그림자
        "outline": 2,
        "shadow": 1,
        "alignment": 2,
        "margin_v": 20,
        "fade_in": 200,
        "fade_out": 200,
    },
    "정석맛": {
        "font_name": config.DEFAULT_FONT,
        "font_size": 24,
        "primary_colour": "&H00FFFFFF",    # 흰색
        "secondary_colour": "&H0000FFFF",  # 노란색 (카라오케 하이라이트)
        "outline_colour": "&H00000000",    # 검정 외곽선
        "back_colour": "&H00000000",
        "bold": 0,
        "italic": 0,
        "border_style": 1,
        "outline": 1,
        "shadow": 0,
        "alignment": 2,
        "margin_v": 20,
        "fade_in": 0,
        "fade_out": 0,
    },
}

VALID_PRESET_NAMES = set(PRESETS.keys())


def get_preset(name: str) -> dict:
    if name not in PRESETS:
        raise ValueError(f"알 수 없는 스타일 프리셋: '{name}'. 사용 가능: {sorted(VALID_PRESET_NAMES)}")
    return PRESETS[name]
