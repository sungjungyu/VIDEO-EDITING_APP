"""자막 이벤트(결과 초) + 스타일 → .ass 파일.

예전 media_engine/ass_generator.py를 옮겨 오면서 바꾼 점
    - PlayResX/Y = 출력 해상도. 크기·여백·두께를 실제 픽셀로 쓴다 (예전에는 PlayRes가 없어 기본 288 기준이라
      같은 '24'가 1080p에서 약 90px로 커졌다)
    - 글자 크기는 CSS px → ASS Fontsize로 변환 (fonts.line_ratio) → 미리보기와 같은 크기
    - 배경 상자는 BorderStyle 4 (libass: 상자 + 글자 외곽선 동시, 상자 여백 = Outline + Shadow)
    - 줄바꿈은 timeline 단계에서 미리 넣고 WrapStyle 2(자동 줄바꿈 끔)로 그대로 쓴다
"""

from __future__ import annotations

from ..models import StyleSpec, SubtitleEvent
from . import fonts

REFERENCE_SHORT_SIDE = 1080
SHADOW_ALPHA_HEX = "40"            # 그림자: 검정 75% 불투명
BOX_PAD_RATIO = 0.2                # 상자 안쪽 여백 = 글자 크기의 20%


def ass_color(hex_color: str, opacity_pct: float = 100.0) -> str:
    """#RRGGBB + 불투명도(%) → &HAABBGGRR (ASS 알파는 00=불투명)."""
    h = hex_color.lstrip("#")
    alpha = round((100 - max(0.0, min(100.0, float(opacity_pct)))) / 100 * 255)
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def karaoke_highlight(base_hex: str) -> str:
    """카라오케에서 이미 말한 단어 색. 기본은 노랑, 글자색이 이미 노란 계열이면 흰색."""
    h = base_hex.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "#ffffff" if r > 200 and g > 180 and b < 120 else "#ffe600"


def seconds_to_ass(seconds: float) -> str:
    total_cs = max(0, round(seconds * 100))
    cs, total_s = total_cs % 100, total_cs // 100
    return f"{total_s // 3600}:{total_s // 60 % 60:02d}:{total_s % 60:02d}.{cs:02d}"


def escape_text(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")


def style_name(style_id: str) -> str:
    if style_id == "subtitle":
        return "Default"
    return "S_" + "".join(ch if ch.isalnum() else "_" for ch in style_id)


def style_values(spec: StyleSpec, out_w: int, out_h: int) -> dict:
    """ASS 스타일 한 줄에 들어갈 값 (실제 픽셀). 미리보기 CSS도 같은 규칙을 따른다 (static/js/style.js)."""
    scale = min(out_w, out_h) / REFERENCE_SHORT_SIDE
    bold = spec.weight in ("bold", "extra-bold")
    outline = spec.outline_width * scale if spec.outline else 0.0
    if spec.background_box:
        border_style = 4
        pad = max(4.0, spec.size * BOX_PAD_RATIO) * scale
        shadow = max(0.0, pad - outline)
        back = ass_color(spec.bg_color, spec.bg_opacity)
    else:
        border_style = 1
        shadow = spec.shadow_distance * scale if spec.shadow else 0.0
        back = f"&H{SHADOW_ALPHA_HEX}000000"
    primary = karaoke_highlight(spec.color) if spec.karaoke else spec.color
    return {
        "font": spec.font,
        "size": round(spec.size * scale * fonts.line_ratio(spec.font, bold), 2),
        "primary": ass_color(primary),
        "secondary": ass_color(spec.color),
        "outline_colour": ass_color(spec.outline_color),
        "back": back,
        "bold": -1 if bold else 0,
        "italic": -1 if spec.italic else 0,
        "border_style": border_style,
        "outline": round(outline, 2),
        "shadow": round(shadow, 2),
        "alignment": {"top": 8, "center": 5, "bottom": 2}[spec.position],
        "margin_lr": round(out_w * 0.05),
        "margin_v": round(spec.bottom_margin * scale),
    }


def _style_line(name: str, v: dict) -> str:
    return (f"Style: {name},{v['font']},{v['size']},{v['primary']},{v['secondary']},{v['outline_colour']},"
            f"{v['back']},{v['bold']},{v['italic']},0,0,100,100,0,0,{v['border_style']},{v['outline']},"
            f"{v['shadow']},{v['alignment']},{v['margin_lr']},{v['margin_lr']},{v['margin_v']},1")


def karaoke_text(event: SubtitleEvent) -> str:
    """단어 시각으로 \\k 태그를 만든다. word_lines에 따라 줄 사이에 \\N."""
    parts: list[str] = []
    prev_end = event.start
    prev_line = event.word_lines[0] if event.word_lines else 0
    for w, line_no in zip(event.words, event.word_lines):
        if line_no != prev_line:
            parts.append("\\N")
            prev_line = line_no
        elif parts:
            parts.append(" ")
        gap = round((w.start - prev_end) * 100)
        if gap > 0:
            parts.append(f"{{\\k{gap}}}")
        dur = max(1, round((w.end - max(w.start, prev_end)) * 100))
        parts.append(f"{{\\k{dur}}}{escape_text(w.word)}")
        prev_end = max(prev_end, w.end)
    return "".join(parts)


def build_ass(events: list[SubtitleEvent], styles: dict[str, StyleSpec], out_w: int, out_h: int) -> str:
    used = sorted({e.style for e in events} | {"subtitle"})
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {out_w}",
        f"PlayResY: {out_h}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
    ]
    for style_id in used:
        spec = styles.get(style_id) or styles.get("subtitle") or StyleSpec()
        lines.append(_style_line(style_name(style_id), style_values(spec, out_w, out_h)))
    lines += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for event in sorted(events, key=lambda e: (e.start, e.style)):
        if event.end - event.start < 0.04:
            continue
        spec = styles.get(event.style) or styles.get("subtitle") or StyleSpec()
        prefix = "{\\fad(150,150)}" if spec.fade else ""
        if spec.karaoke and event.words and len(event.word_lines) == len(event.words):
            body = karaoke_text(event)
        else:
            body = "\\N".join(escape_text(part) for part in event.text.split("\n"))
        layer = 0 if event.style == "subtitle" else 1
        lines.append(f"Dialogue: {layer},{seconds_to_ass(event.start)},{seconds_to_ass(event.end)},"
                     f"{style_name(event.style)},,0,0,0,,{prefix}{body}")
    return "\n".join(lines) + "\n"
