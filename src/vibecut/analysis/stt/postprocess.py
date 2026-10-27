"""받아쓰기 결과 정리: 엔진 출력을 믿지 않고 코드로 다듬는다 (모두 '클립 초').

    drop_hallucinations   말소리가 없는데 Whisper가 지어낸 세그먼트 제외
    clean_segments        범위 자르기·정렬·단어 시각 단조 증가·빈 세그먼트 제거
    refine_with_silence   무음 경계에 단어 경계 맞추기 (analysis.audio)
    split_into_sentences  2~3문장 덩어리를 문장 단위로 다시 나누기
"""

from __future__ import annotations

from ...domain.korean import bigram_overlap, letters_only
from ...domain.text import squash
from ..audio import Silence
from .engines import split_sentences


def hallucination_reason(seg: dict, initial_prompt: str = "") -> str | None:
    """말소리가 없는데 Whisper가 지어낸 세그먼트면 이유를, 아니면 None을 돌려준다 (원본 세그먼트 기준).
    실측: 소음만 있는 10초 클립에서 initial_prompt 문구를 섞어 그대로 출력함
    (no_speech_prob 0.59, 평균 단어 확률 0.17. 실제 말소리는 소음이 있어도 0.93)."""
    text = str(seg.get("text", ""))
    echo = bigram_overlap(letters_only(text), letters_only(initial_prompt)) if initial_prompt else 0.0
    if initial_prompt and len(squash(text)) >= 6 and echo >= 0.6:
        return "안내 문구(initial_prompt) 반복"
    probs = [float(w["probability"]) for w in seg.get("words") or [] if w.get("probability") is not None]
    no_speech = seg.get("no_speech_prob")
    if probs and no_speech is not None:
        mean_p = sum(probs) / len(probs)
        if mean_p < 0.4 and no_speech >= 0.4:
            return f"말소리 아님 (단어 확률 {mean_p:.2f}, 무음 확률 {no_speech:.2f})"
    return None


def drop_hallucinations(raw: list, initial_prompt: str = "") -> tuple[list, list]:
    """(남길 세그먼트, 버린 세그먼트)로 나눈다. 버린 것도 결과 파일에 이유와 함께 남긴다."""
    kept, dropped = [], []
    for s in raw or []:
        reason = hallucination_reason(s, initial_prompt)
        if reason:
            dropped.append({"start": s.get("start"), "end": s.get("end"),
                            "text": str(s.get("text", "")).strip(), "reason": reason})
        else:
            kept.append(s)
    return kept, dropped


def clean_segments(raw: list, duration: float) -> list[dict]:
    """엔진 출력을 믿지 않고 코드로 정리한다 (클립 기준 초).
    - 단어 앞뒤 공백 제거, 빈 단어·시각 없는 단어 제거
    - 모든 시각을 0~duration으로 자르기
    - 세그먼트 경계를 넘어서도 단어 시각이 줄어들지 않게(단조 증가) 맞추기
    - 단어가 있으면 세그먼트 start/end를 첫 단어 시작·마지막 단어 끝으로 맞추기
    - 내용 없는 세그먼트 제거, 끝 시각 순 정렬
      (엔진은 문장 첫 단어의 시작을 크게 틀리는 경우가 있다. 실측: Gemini가 첫 단어 시작을 10초 앞당김,
       Whisper가 1.1초 앞당김. 시작 순으로 정렬하면 순서가 뒤바뀌어 앞 문장이 찌그러진다.)
    """
    def clamp(x: float) -> float:
        return max(0.0, min(x, duration))

    segs = []
    for s in raw or []:
        try:
            st, en = clamp(float(s.get("start", 0))), clamp(float(s.get("end", 0)))
        except (TypeError, ValueError):
            continue
        words = []
        for w in s.get("words") or []:
            text = str(w.get("word", "")).strip()
            if not text:
                continue
            try:
                ws, we = clamp(float(w["start"])), clamp(float(w["end"]))
            except (KeyError, TypeError, ValueError):
                continue
            word = {"word": text, "start": ws, "end": we}
            if w.get("probability") is not None:
                word["probability"] = round(float(w["probability"]), 3)
            words.append(word)
        text = str(s.get("text", "")).strip() or " ".join(w["word"] for w in words)
        if not text:
            continue
        seg = {"start": st, "end": max(st, en), "text": text, "words": words}
        if s.get("speaker"):
            seg["speaker"] = str(s["speaker"])
        segs.append(seg)

    segs.sort(key=lambda x: (x["end"], x["start"]))
    prev_end = 0.0
    for seg in segs:
        for w in seg["words"]:
            w["start"] = max(w["start"], prev_end)
            w["end"] = max(w["end"], w["start"])
            prev_end = w["end"]
        if seg["words"]:
            seg["start"], seg["end"] = seg["words"][0]["start"], seg["words"][-1]["end"]
        else:
            seg["start"] = max(seg["start"], prev_end)
            seg["end"] = max(seg["end"], seg["start"])
            prev_end = seg["end"]
    return segs


def refine_with_silence(segs: list[dict], silences: list[Silence], reach: float = 0.3) -> list[dict]:
    """무음 경계에 단어 경계를 맞춘다 (clean_segments 결과를 받아 제자리에서 고친다).
    - 단어 시작이 무음 안에 있으면 → 무음이 끝나는 시점으로 미룬다
    - 단어 끝이 무음 안에 있으면   → 무음이 시작하는 시점으로 당긴다
    - 단어 시작 직전(reach초 이내)에 무음이 끝나면 → 그때부터 말한 것이므로 시작을 당긴다
    - 단어 끝 직후(reach초 이내)에 무음이 시작하면 → 그때까지 말한 것이므로 끝을 늘린다
    - 단어가 무음을 통째로 품고 있고 그 무음이 단어 앞쪽(reach초 이내)에 있으면 → 무음 뒤에서 시작한 것으로 본다
      (끝 쪽도 같은 방식. 실측: Gemini가 "오후에는"을 앞 문장 끝에 붙여 0.8초 무음까지 포함시킴)
    앞뒤 단어를 넘어서지 않으므로 단어 시각 순서는 유지된다.
    한 단어를 고치면 이웃 단어의 판단이 바뀔 수 있어 두 번 돌린다."""
    words = [w for s in segs for w in s["words"]]
    for _ in range(2):
        for i, w in enumerate(words):
            prev_end = words[i - 1]["end"] if i else 0.0
            next_start = words[i + 1]["start"] if i + 1 < len(words) else float("inf")
            for s, e in silences:
                if s <= w["start"] < e:
                    w["start"] = min(e, w["end"])
                elif prev_end <= e < w["start"] <= e + reach:
                    w["start"] = e
                elif w["start"] <= s and e < w["end"] and s - w["start"] <= reach:
                    w["start"] = e
                if s < w["end"] <= e:
                    w["end"] = max(s, w["start"])
                elif w["end"] < s <= min(w["end"] + reach, next_start):
                    w["end"] = s
                elif w["start"] < s and e <= w["end"] and w["end"] - e <= reach:
                    w["end"] = s
    for seg in segs:
        if seg["words"]:
            seg["start"], seg["end"] = seg["words"][0]["start"], seg["words"][-1]["end"]
    return segs


def split_into_sentences(segments: list[dict]) -> list[dict]:
    """Whisper는 2~3문장을 한 덩어리로 묶는다 ("음. 라떼가 유명하다고. 아 다시 할게. …").
    덩어리째 자르면 살려야 할 문장까지 잘리므로, 단어 시각과 문장부호·쉼으로 문장 단위로 다시 나눈다
    (Gemini 받아쓰기와 같은 기준: split_sentences)."""
    out = []
    for seg in segments:
        words = seg.get("words") or []
        if len(words) < 2:
            out.append(seg)
            continue
        for group in split_sentences(words):
            item = {"start": group[0]["start"], "end": group[-1]["end"],
                    "text": " ".join(w["word"] for w in group), "words": group}
            if seg.get("speaker"):
                item["speaker"] = seg["speaker"]
            out.append(item)
    return out
