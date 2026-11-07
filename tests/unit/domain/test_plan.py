"""편집 계획 값 범위: API로 들어온 값·예전 plan.json 값을 렌더가 감당할 수 있게 맞춘다 (거절하지 않는다)."""

from __future__ import annotations

from vibecut.domain.models import EditPlan, OutputSpec, PlanOptions, StyleSpec
from vibecut.domain.models.plan import SUBTITLE_FONTS
from vibecut.render.ass import build_ass
from vibecut.render.fonts import FONT_FAMILIES


def test_output_size_is_even_and_bounded():
    assert OutputSpec(resolution=1081).size() == (1920, 1080)    # 홀수 → 짝수 (libx264 yuv420p)
    assert OutputSpec(resolution=100000).resolution == 2160
    assert OutputSpec(resolution=0).resolution == 360
    assert OutputSpec(fps=0).fps == 12 and OutputSpec(fps=1000).fps == 60


def test_style_font_and_sizes_are_safe_for_ass():
    style = StyleSpec(font="Arial,0,0\nDialogue: 0,0:00:00.00,9:00:00.00,Default,,0,0,0,,해킹", size=-5,
                      outline_width=float("nan"), bg_opacity=500)
    assert style.font == "Malgun Gothic"
    assert style.size == 8 and style.outline_width == 0 and style.bg_opacity == 100
    assert StyleSpec(font="noto sans kr").font == "Noto Sans KR"
    assert "해킹" not in build_ass([], {"subtitle": style}, 1920, 1080)


def test_plan_options_bounded():
    opts = PlanOptions(punch_scale=0.5, fade_ms=-3, pad_start=-1, title_text="가" * 500)
    assert opts.punch_scale == 1.0 and opts.fade_ms == 0 and opts.pad_start == 0
    assert len(opts.title_text) == 200


def test_old_plan_json_with_bad_values_still_loads():
    plan = EditPlan.model_validate({"output": {"resolution": 1081, "fps": 0},
                                    "styles": {"subtitle": {"font": "Comic Sans", "size": 9999}}})
    assert plan.output.resolution == 1080 and plan.styles["subtitle"].size == 300


def test_subtitle_fonts_match_render_font_files():
    assert set(SUBTITLE_FONTS) == set(FONT_FAMILIES)
