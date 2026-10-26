"""글꼴 파일 찾기와 '미리보기(CSS) = 렌더(ASS)' 크기 맞추기.

CSS font-size는 em 크기다. libass는 ASS Fontsize를 '(usWinAscent + usWinDescent)' 높이로 맞춘다
(libass ass_font.c: OS/2 win 값을 ascender/descender로 쓰고 FT_SIZE_REQUEST_TYPE_REAL_DIM으로 크기 요청).
그래서 같은 글자 크기를 보이려면  ASS Fontsize = CSS px × (winAscent + winDescent) / unitsPerEm.
이 비율(line_ratio)은 CSS line-height로도 쓴다 → 줄 높이까지 같아진다.
"""

from __future__ import annotations

import logging
import os
import struct
import sys
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("vibecut.render.fonts")

DEFAULT_RATIO = 1.3

# 화면에서 고를 수 있는 글꼴 → (보통, 굵게) 파일 이름 후보 (Windows / macOS / Linux 공통 이름)
KNOWN_FONTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "malgun gothic": (("malgun.ttf",), ("malgunbd.ttf",)),
    "nanumgothic": (("NanumGothic.ttf",), ("NanumGothicBold.ttf",)),
    "nanummyeongjo": (("NanumMyeongjo.ttf",), ("NanumMyeongjoBold.ttf",)),
    "noto sans kr": (("NotoSansKR-Regular.otf", "NotoSansKR-Regular.ttf", "NotoSansKR-VF.ttf"),
                     ("NotoSansKR-Bold.otf", "NotoSansKR-Bold.ttf", "NotoSansKR-VF.ttf")),
    "arial": (("arial.ttf", "Arial.ttf"), ("arialbd.ttf", "Arial Bold.ttf")),
}
FALLBACK_FAMILY = "Malgun Gothic" if sys.platform == "win32" else "NanumGothic"


def font_dirs() -> list[Path]:
    dirs = []
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", "C:/Windows")
        dirs.append(Path(windir) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
                 Path("/Library/Fonts"), Path.home() / "Library/Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
                 Path.home() / ".local/share/fonts"]
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=64)
def find_font_file(family: str, bold: bool = False) -> Path | None:
    names = KNOWN_FONTS.get(family.strip().lower())
    if not names:
        return None
    candidates = names[1] + names[0] if bold else names[0]
    for directory in font_dirs():
        for name in candidates:
            direct = directory / name
            if direct.exists():
                return direct
        # 리눅스는 하위 폴더(truetype/nanum/…)에 있다
        if sys.platform not in ("win32",):
            for name in candidates:
                hit = next(directory.rglob(name), None)
                if hit:
                    return hit
    return None


def _read_tables(data: bytes, offset: int = 0) -> dict[str, tuple[int, int]]:
    num_tables = struct.unpack_from(">H", data, offset + 4)[0]
    tables = {}
    for i in range(num_tables):
        tag, _checksum, table_offset, length = struct.unpack_from(">4sIII", data, offset + 12 + 16 * i)
        tables[tag.decode("latin-1")] = (table_offset, length)
    return tables


def line_ratio_from_bytes(data: bytes) -> float:
    """TTF/OTF/TTC 바이트에서 (winAscent + winDescent) / unitsPerEm 을 계산한다."""
    offset = 0
    if data[:4] == b"ttcf":                 # 글꼴 모음은 첫 번째 글꼴을 쓴다
        offset = struct.unpack_from(">I", data, 12)[0]
    tables = _read_tables(data, offset)
    head_off = tables["head"][0]
    units_per_em = struct.unpack_from(">H", data, head_off + 18)[0]
    if "OS/2" in tables:
        os2 = tables["OS/2"][0]
        win_ascent, win_descent = struct.unpack_from(">HH", data, os2 + 74)
        if win_ascent + win_descent > 0:
            return (win_ascent + win_descent) / units_per_em
        typo_ascender, typo_descender = struct.unpack_from(">hh", data, os2 + 68)
        if typo_ascender - typo_descender > 0:
            return (typo_ascender - typo_descender) / units_per_em
    hhea = tables["hhea"][0]
    ascender, descender = struct.unpack_from(">hh", data, hhea + 4)
    return (ascender - descender) / units_per_em


@lru_cache(maxsize=64)
def line_ratio(family: str, bold: bool = False) -> float:
    path = find_font_file(family, bold) or find_font_file(FALLBACK_FAMILY, bold)
    if path is None:
        return DEFAULT_RATIO
    try:
        ratio = line_ratio_from_bytes(path.read_bytes())
    except (struct.error, KeyError, OSError) as error:
        log.warning("글꼴 메트릭을 읽지 못했습니다 (%s): %s", path.name, error)
        return DEFAULT_RATIO
    return ratio if 0.8 <= ratio <= 2.5 else DEFAULT_RATIO


def font_metrics_table() -> dict[str, float]:
    """화면에서 쓰는 글꼴별 비율 (/api/config로 프론트에 넘긴다)."""
    labels = {"malgun gothic": "Malgun Gothic", "nanumgothic": "NanumGothic", "nanummyeongjo": "NanumMyeongjo",
              "noto sans kr": "Noto Sans KR", "arial": "Arial"}
    return {label: round(line_ratio(label), 4) for label in labels.values()}


def available_fonts() -> dict[str, bool]:
    return {label: find_font_file(label) is not None
            for label in ("Malgun Gothic", "NanumGothic", "NanumMyeongjo", "Noto Sans KR", "Arial")}
