from . import config


PRESETS: dict[str, dict] = {
    "매운맛": {
        "font_name": config.DEFAULT_FONT,
        "font_size": 28,
        "primary_colour": "&H0000FFFF",
        "secondary_colour": "&H000000FF",
        "outline_colour": "&H00000000",
        "back_colour": "&H80000000",
        "bold": 1,
        "italic": 0,
        "border_style": 3,
        "outline": 2,
        "shadow": 1,
        "alignment": 2,
        "margin_v": 30,
        "fade_in": 150,
        "fade_out": 150,
    },
    "순한맛": {
        "font_name": config.DEFAULT_FONT,
        "font_size": 22,
        "primary_colour": "&H00FFFFFF",
        "secondary_colour": "&H0000FFFF",
        "outline_colour": "&H00000000",
        "back_colour": "&H00000000",
        "bold": 0,
        "italic": 0,
        "border_style": 1,
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
        "primary_colour": "&H00FFFFFF",
        "secondary_colour": "&H0000FFFF",
        "outline_colour": "&H00000000",
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

VALID_PRESET_NAMES = set(PRESETS)


def get_preset(name: str) -> dict:
    if name not in PRESETS:
        raise ValueError(
            f"알 수 없는 스타일 프리셋: '{name}'. "
            f"사용 가능: {sorted(VALID_PRESET_NAMES)}"
        )
    return PRESETS[name]
