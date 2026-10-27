"""ASS 자막 생성 테스트: 색·시각·이스케이프, 출력 크기에 따른 스타일 값, 배경 상자, 이벤트."""

from __future__ import annotations

import pytest

from vibecut.domain.models import StyleSpec, SubtitleEvent, Word
from vibecut.render import ass, fonts


def test_colors_times_and_escape():
    assert ass.ass_color("#ffe000") == "&H0000E0FF"
    assert ass.ass_color("#d00000", 70) == "&H4C0000D0"
    assert ass.seconds_to_ass(3723.456) == "1:02:03.46"
    assert ass.escape_text("{\\태그}") == "｛＼태그｝"


@pytest.fixture
def fixed_ratio(monkeypatch):
    monkeypatch.setattr(fonts, "line_ratio", lambda family, bold=False: 1.25)


def test_style_values_scale_with_output_size(fixed_ratio):
    spec = StyleSpec(size=54, outline_width=3, bottom_margin=60)
    full = ass.style_values(spec, 1920, 1080)
    half = ass.style_values(spec, 960, 540)
    vertical = ass.style_values(spec, 1080, 1920)
    assert full["size"] == pytest.approx(54 * 1.25)
    assert half["size"] == pytest.approx(54 * 1.25 / 2)
    assert vertical["size"] == full["size"]                 # 짧은 변 기준이라 세로 영상도 같은 크기
    assert (full["outline"], full["margin_v"], half["margin_v"]) == (3.0, 60, 30)


def test_box_style_uses_borderstyle_4_with_padding(fixed_ratio):
    spec = StyleSpec(size=50, background_box=True, bg_color="#000000", bg_opacity=60, outline=True, outline_width=2)
    v = ass.style_values(spec, 1920, 1080)
    assert v["border_style"] == 4
    assert v["outline"] + v["shadow"] == pytest.approx(10.0)    # 상자 여백 = 글자 크기 20%
    assert v["back"] == "&H66000000"


def test_build_ass_events(fixed_ratio):
    styles = {"subtitle": StyleSpec(karaoke=True, fade=True), "title": StyleSpec(size=80, position="top")}
    events = [
        SubtitleEvent(start=0.0, end=2.0, text="안녕\n반가워", words=[Word(word="안녕", start=0.1, end=0.5),
                                                                  Word(word="반가워", start=0.8, end=1.5)],
                      word_lines=[0, 1]),
        SubtitleEvent(start=2.0, end=4.0, text="제목", style="title"),
    ]
    text = ass.build_ass(events, styles, 1920, 1080)
    assert "PlayResX: 1920" in text and "PlayResY: 1080" in text and "WrapStyle: 2" in text
    assert "Style: S_title," in text
    dialogue = [row for row in text.splitlines() if row.startswith("Dialogue")]
    assert "{\\fad(150,150)}{\\k10}{\\k40}안녕\\N{\\k30}{\\k70}반가워" in dialogue[0]
    assert dialogue[1].startswith("Dialogue: 1,0:00:02.00,0:00:04.00,S_title")
