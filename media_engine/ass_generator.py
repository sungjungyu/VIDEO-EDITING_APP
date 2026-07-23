"""
편집 JSON + 스타일 프리셋 → .ass 자막 파일 생성

ASS 포맷 참고:
  - \\k<centiseconds>  : 카라오케 타이밍 (100분의 1초 단위)
  - \\fad(<in>,<out>)  : 페이드인/아웃 (밀리초)
  - BorderStyle=3      : 불투명 배경 박스(필박스)
  - BorderStyle=1      : 외곽선 + 그림자
"""
from .style_presets import get_preset
from .exceptions import SubtitleGenerationError


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
    style_preset: str,
    output_path: str,
    style_overrides: dict | None = None,
) -> None:
    """
    subtitles      : timestamp_mapper 거친 자막 리스트
    style_preset   : "매운맛" | "순한맛" | "정석맛"
    output_path    : 생성할 .ass 파일 경로
    style_overrides: 프론트엔드에서 전달한 세부 설정 (프리셋 기본값을 덮어씀)
                     keys: font, color, size, outline, outline_width,
                           background_box, karaoke, fade
    """
    try:
        preset = dict(get_preset(style_preset))   # 원본 변경 방지를 위해 복사
    except ValueError as e:
        raise SubtitleGenerationError(str(e)) from e

    if style_overrides:
        ov = style_overrides
        if ov.get("font"):
            preset["font_name"] = ov["font"]
        if ov.get("color"):
            preset["primary_colour"] = _css_hex_to_ass(ov["color"])
        if ov.get("size") is not None:
            preset["font_size"] = int(ov["size"])
        # 외곽선 on/off + 두께
        if ov.get("outline") is not None:
            if not ov["outline"]:
                preset["outline"] = 0
                preset["shadow"]  = 0
            elif ov.get("outline_width") is not None:
                preset["outline"] = float(ov["outline_width"])
        elif ov.get("outline_width") is not None:
            preset["outline"] = float(ov["outline_width"])
        # 배경 박스 (BorderStyle 3=필박스 / 1=외곽선)
        if ov.get("background_box") is not None:
            preset["border_style"] = 3 if ov["background_box"] else 1
        # 카라오케 off → words 있어도 일반 텍스트로 강제
        if ov.get("karaoke") is not None:
            preset["_karaoke"] = bool(ov["karaoke"])
        # 페이드 on/off
        if ov.get("fade") is not None:
            if ov["fade"]:
                preset.setdefault("fade_in",  150)
                preset.setdefault("fade_out", 150)
            else:
                preset["fade_in"]  = 0
                preset["fade_out"] = 0

    try:
        lines = _render_ass(subtitles, preset)
        with open(output_path, "w", encoding="utf-8-sig") as f:
            f.write(lines)
    except SubtitleGenerationError:
        raise
    except Exception as e:
        raise SubtitleGenerationError(f".ass 파일 생성 실패: {e}") from e


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
