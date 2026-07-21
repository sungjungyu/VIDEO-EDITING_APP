"""
편집 JSON + 스타일 프리셋 → .ass 자막 파일 생성

ASS 포맷 참고:
  - \k<centiseconds>  : 카라오케 타이밍 (100분의 1초 단위)
  - \fad(<in>,<out>)  : 페이드인/아웃 (밀리초)
  - BorderStyle=3     : 불투명 배경 박스(필박스)
  - BorderStyle=1     : 외곽선 + 그림자
"""
import math
from .style_presets import get_preset
from .exceptions import SubtitleGenerationError


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
    words 리스트로 카라오케 \k 태그 텍스트를 생성한다.
    \k 값은 이전 단어 끝~현재 단어 끝까지의 길이(centiseconds).
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
) -> None:
    """
    subtitles: timestamp_mapper 거친 자막 리스트
    style_preset: "매운맛" | "순한맛" | "정석맛"
    output_path: 생성할 .ass 파일 경로
    """
    try:
        preset = get_preset(style_preset)
    except ValueError as e:
        raise SubtitleGenerationError(str(e)) from e

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

    event_lines = []
    for sub in subtitles:
        start = _seconds_to_ass(sub["start"])
        end = _seconds_to_ass(sub["end"])

        fade = ""
        fi = preset.get("fade_in", 0)
        fo = preset.get("fade_out", 0)
        if fi or fo:
            fade = f"{{\\fad({fi},{fo})}}"

        if sub.get("words"):
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
