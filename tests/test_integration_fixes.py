"""yonggwan-test 통합 점검에서 고친 버그들의 회귀 테스트 (docs/통합테스트_병합기록.md 참고)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import VideoEditingPipeline
from media_engine import ass_generator

SEGS = [{"start": 0.0, "end": 2.7, "text": "가"}, {"start": 2.7, "end": 5.0, "text": "나"},
        {"start": 5.0, "end": 8.0, "text": "다"}]
PRETTY = json.dumps([{**s, "cut": i == 1} for i, s in enumerate(SEGS)], ensure_ascii=False, indent=1)


def run_step3(response: str):
    pipeline = VideoEditingPipeline.__new__(VideoEditingPipeline)
    with patch.object(VideoEditingPipeline, "_call_gemini", return_value=response):
        return pipeline.step3_analyze_context(SEGS, {})


class Step3JsonTests(unittest.TestCase):
    def test_pretty_printed_multi_object_json_is_used(self):
        # 예전 복구 로직은 "}," 줄을 지워서 이 경우 항상 로컬 명령으로 대체됐다
        out = run_step3(PRETTY)
        self.assertEqual([o["cut"] for o in out], [False, True, False])

    def test_truncated_response_keeps_complete_objects_and_backfills_rest(self):
        cut_at = PRETTY.index("{", PRETTY.index("{", 2) + 1)          # 두 번째 객체 시작에서 자름
        out = run_step3(PRETTY[:cut_at] + '{\n"start": 2')
        self.assertEqual([(o["start"], o["end"]) for o in out], [(0.0, 2.7), (2.7, 5.0), (5.0, 8.0)])

    def test_broken_middle_falls_back_to_local_commands(self):
        out = run_step3(PRETTY.replace("},", "}", 1))
        self.assertEqual(len(out), 3)


class GeminiRetryTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = VideoEditingPipeline.__new__(VideoEditingPipeline)
        self.pipeline.gemini_model_name = "gemini-3.5-flash"

    def test_transient_errors_retry_then_fallback_model(self):
        calls = []

        def flaky(prompt, model):
            calls.append(model)
            if len(calls) < 3:
                raise RuntimeError("503 UNAVAILABLE")
            return "[]"
        with patch.object(VideoEditingPipeline, "_call_gemini_once", side_effect=flaky), patch("main.time.sleep"):
            self.assertEqual(self.pipeline._call_gemini("x"), "[]")
        self.assertEqual(calls, ["gemini-3.5-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"])

    def test_non_transient_error_is_not_retried(self):
        with patch.object(VideoEditingPipeline, "_call_gemini_once", side_effect=ValueError("400")) as m:
            with self.assertRaises(ValueError):
                self.pipeline._call_gemini("x")
        self.assertEqual(m.call_count, 1)


class SubtitleStyleTests(unittest.TestCase):
    def render(self, **kwargs) -> str:
        path = Path(tempfile.mkdtemp()) / "a.ass"
        ass_generator.generate([{"start": 0, "end": 1, "text": "안녕"}], str(path), **kwargs)
        return path.read_text(encoding="utf-8-sig")

    def style_line(self, ass: str) -> list[str]:
        return next(l for l in ass.splitlines() if l.startswith("Style: Default,")).split(",")

    def test_default_style_without_settings(self):
        s = self.style_line(self.render())
        self.assertEqual((s[1], s[2], s[3]), ("Malgun Gothic", "24", "&H00FFFFFF"))

    def test_style_panel_settings_are_applied(self):
        ass = self.render(style_overrides={"color": "#FFE000", "size": 40, "weight": "bold", "italic": True,
                                           "background_box": True, "bg_color": "#D00000", "bg_opacity": 70,
                                           "position": "top", "bottom_margin": 15, "fade": True})
        s = self.style_line(ass)
        self.assertEqual(s[2], "40")                 # 크기
        self.assertEqual(s[3], "&H0000E0FF")         # #FFE000 → BGR
        self.assertEqual((s[7], s[8]), ("1", "1"))   # 굵게, 기울임
        self.assertEqual(s[15], "3")                 # 배경 상자
        self.assertEqual(s[5], "&H4C0000D0")         # 상자 색 #D00000, 불투명도 70% → 알파 76(4C)
        self.assertEqual(s[18], "8")                 # 위쪽
        self.assertIn("\\fad(150,150)", ass)         # 카라오케가 꺼져 있어도 페이드 적용

    def test_unknown_preset_does_not_fail_render(self):
        s = self.style_line(self.render(style_preset="없는맛"))
        self.assertEqual(s[2], "24")


if __name__ == "__main__":
    unittest.main()
