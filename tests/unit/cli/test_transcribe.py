"""받아쓰기 명령의 결과 만들기: 클립 정렬, 전체 타임라인 시각, 결과 검증, 렌더 엔진 연결."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from vibecut.analysis.stt.postprocess import clean_segments
from vibecut.cli import clips as clip_tools
from vibecut.cli.transcribe import globalize, validate_transcript
from vibecut.domain.models import KeepRange, Line, StyleSpec, Word
from vibecut.editing.subtitles import build_subtitle_events
from vibecut.render.ass import karaoke_text

RAW_C01 = [
    {"start": 0.0, "end": 2.0, "text": " 안녕하세요 오늘은",
     "words": [{"word": " 안녕하세요", "start": 0.2, "end": 0.9, "probability": 0.98},
               {"word": " 오늘은", "start": 1.0, "end": 1.6, "probability": 0.91}]},
    {"start": 2.0, "end": 4.0, "text": " 카페에 왔어요.",
     "words": [{"word": " 카페에", "start": 2.1, "end": 2.6, "probability": 0.95},
               {"word": " 왔어요.", "start": 2.7, "end": 3.4, "probability": 0.42}]},
]
RAW_C02 = [
    {"start": 0.5, "end": 1.5, "text": " 맛있다",
     "words": [{"word": " 맛있다", "start": 0.5, "end": 1.2, "probability": 0.9}]},
]


def build_transcript(clips, raw_by_clip):
    """명령과 같은 순서로 transcript dict를 만든다 (받아쓰기 엔진 없이)."""
    segments = []
    for c in clips:
        segments += globalize(clean_segments(raw_by_clip[c["id"]], c["duration"]), c)
    for i, s in enumerate(segments, 1):
        s["seg_id"] = f"t{i:04d}"
    return {
        "clips": [{"id": c["id"], "duration": c["duration"], "offset": round(c["offset"], 2)} for c in clips],
        "segments": segments,
    }


@pytest.fixture
def transcript():
    clips = [{"id": "c01", "duration": 10.0, "offset": 0.0}, {"id": "c02", "duration": 8.0, "offset": 10.0}]
    return build_transcript(clips, {"c01": RAW_C01, "c02": RAW_C02})


def test_sorts_by_created_then_name_and_sets_offsets():
    info = {"b.mp4": {"duration": 10.0, "created": 100.0},
            "a.mp4": {"duration": 20.0, "created": 200.0},
            "c.mp4": {"duration": 5.0, "created": 100.0}}
    with patch.object(clip_tools, "probe", side_effect=lambda p: info[p.name]):
        clips = clip_tools.order_clips([Path("a.mp4"), Path("c.mp4"), Path("b.mp4")])
    assert [(c["id"], c["file"].name, c["offset"]) for c in clips] == \
        [("c01", "b.mp4", 0.0), ("c02", "c.mp4", 10.0), ("c03", "a.mp4", 15.0)]


def test_global_times_and_clip_times(transcript):
    s = transcript["segments"][2]
    assert (s["seg_id"], s["clip_id"]) == ("t0003", "c02")
    assert (s["start"], s["end"]) == (10.5, 11.2)
    assert (s["clip_start"], s["clip_end"]) == (0.5, 1.2)
    assert s["words"][0]["start"] == 10.5


def test_valid_transcript_has_no_problems(transcript):
    assert validate_transcript(transcript) == []


def test_detects_text_words_mismatch_after_edit(transcript):
    transcript["segments"][1]["text"] = "카페에 갔어요."   # 교정 등으로 text만 바뀐 경우
    assert any("t0002" in p and "불일치" in p for p in validate_transcript(transcript))


def test_detects_overlap_and_unknown_clip(transcript):
    transcript["segments"][1]["start"] = 1.0
    transcript["segments"][2]["clip_id"] = "c99"
    problems = validate_transcript(transcript)
    assert any("겹침" in p for p in problems)
    assert any("c99" in p for p in problems)


def test_detects_abnormally_long_word(transcript):
    transcript["segments"][0]["words"][0]["start"] = -3.0
    transcript["segments"][0]["start"] = -3.0
    assert any("비정상적으로 긴 단어" in p for p in validate_transcript(transcript))


def test_speaker_label_is_kept():
    clip = {"id": "c01", "duration": 10.0, "offset": 0.0}
    raw = [{"start": 0, "end": 1, "text": "네", "speaker": "spk:1",
            "words": [{"word": "네", "start": 0.2, "end": 0.6}]}]
    assert globalize(clean_segments(raw, 10.0), clip)[0]["speaker"] == "spk:1"


def test_render_engine_accepts_output(transcript):
    """받아쓰기 결과가 렌더 엔진(자막 장면·카라오케)에 그대로 들어가는지."""
    lines = [Line(seg_id=s["seg_id"], clip_id="c01", start=s["clip_start"], end=s["clip_end"], text=s["text"],
                  words=[Word(word=w["word"], start=w["start"], end=w["end"]) for w in s["words"]])
             for s in transcript["segments"] if s["clip_id"] == "c01"]
    keep = [KeepRange(clip_id="c01", start=2.0, end=4.0)]    # 두 번째 문장만 남기는 컷
    events = build_subtitle_events(keep, {"c01": lines}, {}, StyleSpec(), 2.0)
    assert len(events) == 1
    assert events[0].text == "카페에 왔어요."
    assert events[0].words[0].start == 0.1
    karaoke = karaoke_text(events[0])
    assert "카페에" in karaoke and "\\k" in karaoke
