import unittest
from unittest.mock import patch

from main import VideoEditingPipeline


class GeminiFallbackTests(unittest.TestCase):
    def test_returns_dummy_commands_when_gemini_times_out(self):
        pipeline = VideoEditingPipeline.__new__(VideoEditingPipeline)
        segments = [{"start": 0.0, "end": 1.5, "text": "안녕하세요"}]

        with patch.object(VideoEditingPipeline, "_call_gemini", side_effect=TimeoutError("Gemini request timed out")):
            result = pipeline.step3_analyze_context(segments, "정석맛")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "안녕하세요")
        self.assertIn("subtitle_color", result[0])

    def test_returns_dummy_commands_when_gemini_returns_invalid_json(self):
        pipeline = VideoEditingPipeline.__new__(VideoEditingPipeline)
        segments = [{"start": 0.0, "end": 1.5, "text": "안녕하세요"}]

        with patch.object(VideoEditingPipeline, "_call_gemini", return_value='not json at all'):
            result = pipeline.step3_analyze_context(segments, "정석맛")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "안녕하세요")

    def test_transcript_refinement_preserves_timestamps(self):
        pipeline = VideoEditingPipeline.__new__(VideoEditingPipeline)
        segments = [{"start": 0.0, "end": 1.5, "text": "안녕 하세요"}]

        with patch.object(
            VideoEditingPipeline,
            "_call_gemini",
            return_value='[{"id": 0, "text": "안녕하세요"}]',
        ):
            result = pipeline.step2_refine_transcript(segments)

        self.assertEqual(result[0]["text"], "안녕하세요")
        self.assertEqual(result[0]["start"], 0.0)
        self.assertEqual(result[0]["end"], 1.5)

    def test_transcript_refinement_keeps_original_on_invalid_response(self):
        pipeline = VideoEditingPipeline.__new__(VideoEditingPipeline)
        segments = [{"start": 0.0, "end": 1.5, "text": "안녕 하세요"}]

        with patch.object(VideoEditingPipeline, "_call_gemini", return_value='[]'):
            result = pipeline.step2_refine_transcript(segments)

        self.assertEqual(result, segments)


if __name__ == "__main__":
    unittest.main()
