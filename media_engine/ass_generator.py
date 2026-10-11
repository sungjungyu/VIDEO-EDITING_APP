"""
편집 JSON → .ass 자막 파일 생성

ASS 포맷 참고:
  - \\k<centiseconds>  : 카라오케 타이밍 (100분의 1초 단위)
  - \\fad(<in>,<out>)  : 페이드인/아웃 (밀리초)
  - BorderStyle=3      : 불투명 배경 박스(필박스)
  - BorderStyle=1      : 외곽선 + 그림자
"""
from . import config
from .style_presets import get_preset
from .exceptions import SubtitleGenerationError

DEFAULT_STYLE = {
    "font_name": config.DEFAULT_FONT,   # NanumGothic은 Windows에 없어 한글이 깨질 수 있음
    "font_size": 24,
    "primary_colour": "&H00FFFFFF",
    "secondary_colour": "&H00FFFFFF",
    "outline_colour": "&H00000000",
    "back_colour": "&H00000000",
    "bold": 0,
    "italic": 0,
    "border_style": 1,
    "outline": 1,
    "shadow": 0,
    "alignment": 2,
    "margin_v": 20,
}


def _css_hex_to_ass(hex_color: str) -> str:
    """CSS #RRGGBB → ASS &H00BBGGRR (알파=00, BGR 바이트 순서)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return "&H00FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _seconds_to_ass(seconds: float) -> str:
    """초 → H:MM:SS.cc (ASS 타임코드)"""
    total_cs = round(seconds * 100)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _build_karaoke_text(words: list[dict], sub_start: float) -> str:
    """
    words 리스트로 카라오케 \\k 태그 텍스트를 생성한다.
    \\k 값은 이전 단어 끝~현재 단어 끝까지의 길이(centiseconds).
    """
    parts = []
    prev_end = sub_start
    for w in words:
        gap_cs = max(0, round((w["start"] - prev_end) * 100))
        dur_cs = max(1, round((w["end"] - w["start"]) * 100))
        if gap_cs > 0:
            parts.append(f"{{\\k{gap_cs}}} ")
        parts.append(f"{{\\k{dur_cs}}}{w['word']}")
        prev_end = w["end"]
    return "".join(parts)


def generate(
    subtitles: list[dict],
    output_path: str,
    style_overrides: dict | None = None,
    style_preset: str | None = None,
) -> None:
    """
    subtitles      : timestamp_mapper 거친 자막 리스트
    output_path    : 생성할 .ass 파일 경로
    style_overrides: 프론트엔드 자막 스타일 패널 설정 (프리셋 기본값을 덮어씀)
                     keys: font, color, size, weight, italic, outline, outline_color, outline_width,
                           shadow, shadow_distance, background_box, bg_color, bg_opacity,
                           position, bottom_margin, karaoke, fade
    style_preset   : "매운맛" | "순한맛" | "정석맛". 없거나 모르는 이름이면 DEFAULT_STYLE
    """
    try:
        preset = dict(get_preset(style_preset)) if style_preset else dict(DEFAULT_STYLE)
    except ValueError:
        preset = dict(DEFAULT_STYLE)   # 모르는 프리셋 이름 때문에 렌더 전체가 실패하지 않게

    if style_overrides:
        _apply_overrides(preset, style_overrides)

    try:
        lines = _render_ass(subtitles, preset)
        with open(output_path, "w", encoding="utf-8-sig") as f:
            f.write(lines)
    except SubtitleGenerationError:
        raise
    except Exception as e:
        raise SubtitleGenerationError(f".ass 파일 생성 실패: {e}") from e


def _ass_alpha_colour(hex_color: str, opacity_pct: float) -> str:
    """CSS #RRGGBB + 불투명도(0~100%) → ASS &HAABBGGRR (ASS 알파는 00=불투명, FF=투명)."""
    alpha = round((100 - max(0.0, min(100.0, float(opacity_pct)))) / 100 * 255)
    return f"&H{alpha:02X}" + _css_hex_to_ass(hex_color)[4:]


def _apply_overrides(preset: dict, ov: dict) -> None:
    """프론트엔드 자막 스타일 패널(SUBTITLE_STYLE) 값을 ASS 스타일에 반영한다 (preset을 제자리에서 고침).
    max_chars_per_line(줄바꿈 글자 수)은 아직 반영하지 않는다."""
    if ov.get("font"):
        preset["font_name"] = ov["font"]
    if ov.get("color"):
        preset["primary_colour"] = _css_hex_to_ass(ov["color"])
    if ov.get("size") is not None:
        preset["font_size"] = int(ov["size"])
    if ov.get("weight") is not None:
        preset["bold"] = 1 if ov["weight"] in ("bold", "extra-bold") else 0
    if ov.get("italic") is not None:
        preset["italic"] = 1 if ov["italic"] else 0
    # 외곽선 on/off + 두께 + 색
    if ov.get("outline") is not None and not ov["outline"]:
        preset["outline"] = 0
    elif ov.get("outline_width") is not None:
        preset["outline"] = float(ov["outline_width"])
    if ov.get("outline_color"):
        preset["outline_colour"] = _css_hex_to_ass(ov["outline_color"])
    # 그림자 on/off + 거리
    if ov.get("shadow") is not None:
        preset["shadow"] = float(ov.get("shadow_distance") or 2) if ov["shadow"] else 0
    # 배경 박스 (BorderStyle 3=불투명 상자 / 1=외곽선). 상자 색은 OutlineColour로 그려진다
    if ov.get("background_box") is not None:
        preset["border_style"] = 3 if ov["background_box"] else 1
        if ov["background_box"]:
            box = _ass_alpha_colour(ov.get("bg_color") or "#000000", ov.get("bg_opacity", 60))
            preset["outline_colour"] = preset["back_colour"] = box
            preset["outline"] = max(float(preset.get("outline") or 0), 4)   # 상자 안쪽 여백
    # 위치(위/가운데/아래) + 여백
    if ov.get("position"):
        preset["alignment"] = {"top": 8, "center": 5, "bottom": 2}.get(ov["position"], 2)
    if ov.get("bottom_margin") is not None:
        preset["margin_v"] = int(ov["bottom_margin"])
    # 카라오케 off → words 있어도 일반 텍스트로 강제
    if ov.get("karaoke") is not None:
        preset["_karaoke"] = bool(ov["karaoke"])
    # 페이드 on/off
    if ov.get("fade") is not None:
        if ov["fade"]:
            preset["fade_in"] = preset.get("fade_in") or 150
            preset["fade_out"] = preset.get("fade_out") or 150
        else:
            preset["fade_in"] = 0
            preset["fade_out"] = 0


def _render_ass(subtitles: list[dict], preset: dict) -> str:
    header = _script_info() + _styles_section(preset) + "[Events]\n"
    header += "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"

    use_karaoke = preset.get("_karaoke", True)   # False면 words가 있어도 일반 텍스트 강제

    event_lines = []
    for sub in subtitles:
        start = _seconds_to_ass(sub["start"])
        end = _seconds_to_ass(sub["end"])

        fade = ""
        fi = preset.get("fade_in", 0)
        fo = preset.get("fade_out", 0)
        if fi or fo:
            fade = f"{{\\fad({fi},{fo})}}"

        if sub.get("words") and use_karaoke:
            text = fade + _build_karaoke_text(sub["words"], sub["start"])
        else:
            text = fade + sub["text"].replace("\n", "\\N")

        event_lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,{preset['margin_v']},,{text}"
        )

    return header + "\n".join(event_lines) + "\n"


def _script_info() -> str:
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n\n"
    )


def _styles_section(preset: dict) -> str:
    return (
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,"
        f"{preset['font_name']},"
        f"{preset['font_size']},"
        f"{preset['primary_colour']},"
        f"{preset['secondary_colour']},"
        f"{preset['outline_colour']},"
        f"{preset['back_colour']},"
        f"{preset['bold']},"
        f"{preset['italic']},"
        f"0,0,100,100,0,0,"
        f"{preset['border_style']},"
        f"{preset['outline']},"
        f"{preset['shadow']},"
        f"{preset['alignment']},"
        f"10,10,{preset['margin_v']},1\n\n"
    )
