"""원본 초 ↔ 클립 초 ↔ 결과 초 변환과 자막 이벤트 만들기.

예전 media_engine/timestamp_mapper.remap을 대신한다. 달라진 점
    - 여러 클립 (KeepRange.clip_id)
    - 문장이 일부만 남으면 남은 단어만 자막으로 보여 준다 (단어 시각이 있을 때)
    - 긴 문장은 2줄 이하가 되게 나눠서 보여 준다 (자막 줄바꿈·시각 재계산, 계획서 2-4)
"""

from __future__ import annotations

from ..models import ClipSpan, KeepRange, Line, LineDecision, PlanOptions, StyleSpec, SubtitleEvent, TreeNode, Word
from .text import align_words_to_lines, squash, wrap_text, wrap_tokens

MAX_LINES = 2
MIN_SHOW = 0.7          # 자막은 가능하면 이만큼은 보여 준다 (초)
JOIN_GAP = 0.35         # 다음 자막과 틈이 이보다 짧으면 이어서 보여 준다 (깜빡임 방지)


def global_to_clip(start: float, end: float, spans: list[ClipSpan]) -> list[tuple[str, float, float]]:
    """원본 초 구간 → 클립별 (clip_id, 클립 초 시작, 끝)."""
    out = []
    for span in spans:
        lo, hi = span.offset, span.offset + span.duration
        s, e = max(start, lo), min(end, hi)
        if e > s:
            out.append((span.clip_id, s - lo, e - lo))
    return out


def clip_to_global(clip_id: str, t: float, spans: list[ClipSpan]) -> float | None:
    span = next((s for s in spans if s.clip_id == clip_id), None)
    return None if span is None else span.offset + t


def to_output(clip_id: str, t: float, keep: list[KeepRange]) -> float | None:
    """클립 초 → 결과 초. 잘려 나간 시각이면 None."""
    for k in keep:
        if k.clip_id == clip_id and k.start <= t < k.end:
            return k.out_start + (t - k.start)
    return None


def _shift_words(words: list[Word], k: KeepRange) -> list[Word]:
    out = []
    for w in words:
        s = k.out_start + (max(w.start, k.start) - k.start)
        e = k.out_start + (min(w.end, k.end) - k.start)
        out.append(Word(word=w.word, start=round(s, 3), end=round(max(e, s), 3)))
    return out


def _pieces(keep: list[KeepRange], lines_by_clip: dict[str, list[Line]],
            decisions: dict[str, LineDecision]) -> list[dict]:
    """남는 구간마다 그 안에 보이는 문장 조각."""
    pieces = []
    for k in keep:
        for line in lines_by_clip.get(k.clip_id, []):
            if line.end <= k.start or line.start >= k.end:
                continue
            d = decisions.get(line.seg_id)
            if d is not None and not d.keep:
                continue
            override = d.text.strip() if d is not None and d.text else ""
            if line.words:
                inside = [w for w in line.words if k.start <= (w.start + w.end) / 2 < k.end]
                if not inside:
                    continue
                partial = len(inside) < len(line.words)
                words = _shift_words(inside, k)
                text = " ".join(w.word for w in inside) if partial else (override or line.text)
                if squash(text) != squash("".join(w.word for w in inside)):
                    words = []          # 고친 자막은 단어 시각과 글자가 달라 카라오케 없이 보여 준다
                start = k.out_start + (max(inside[0].start, k.start) - k.start)
                end = k.out_start + (min(inside[-1].end, k.end) - k.start)
            else:
                text = override or line.text
                words = []
                start = k.out_start + (max(line.start, k.start) - k.start)
                end = k.out_start + (min(line.end, k.end) - k.start)
            if end - start < 0.05 or not text.strip():
                continue
            pieces.append({"seg_id": line.seg_id, "start": start, "end": end, "text": text.strip(), "words": words})
    pieces.sort(key=lambda p: p["start"])
    merged: list[dict] = []
    for p in pieces:            # 한 문장이 두 구간에 걸쳐 남으면 다시 한 덩어리로
        prev = merged[-1] if merged else None
        if prev and prev["seg_id"] == p["seg_id"] and p["start"] - prev["end"] < 0.3:
            prev["end"] = p["end"]
            prev["text"] = prev["text"] + " " + p["text"]
            prev["words"] = prev["words"] + p["words"] if prev["words"] and p["words"] else []
        else:
            merged.append(dict(p))
    return merged


def _chunk(piece: dict, max_chars: int) -> list[dict]:
    """2줄을 넘는 문장을 2줄 이하 조각으로 나눈다. 단어 시각이 있으면 그 시각으로, 없으면 글자 수 비율로."""
    text, words = piece["text"], piece["words"]
    if len(wrap_tokens(text, max_chars)) <= MAX_LINES:
        return [piece]
    chunks: list[dict] = []
    if words:
        cur: list[Word] = []
        for w in words:
            trial = cur + [w]
            if cur and len(wrap_tokens(" ".join(x.word for x in trial), max_chars)) > MAX_LINES:
                chunks.append({"text": " ".join(x.word for x in cur), "words": cur,
                               "start": cur[0].start, "end": cur[-1].end})
                cur = [w]
            else:
                cur = trial
        if cur:
            chunks.append({"text": " ".join(x.word for x in cur), "words": cur, "start": cur[0].start,
                           "end": cur[-1].end})
        chunks[0]["start"] = piece["start"]
        chunks[-1]["end"] = piece["end"]
    else:
        tokens = text.split()
        groups, cur_tokens = [], []
        for tok in tokens:
            trial = cur_tokens + [tok]
            if cur_tokens and len(wrap_tokens(" ".join(trial), max_chars)) > MAX_LINES:
                groups.append(cur_tokens)
                cur_tokens = [tok]
            else:
                cur_tokens = trial
        if cur_tokens:
            groups.append(cur_tokens)
        total_chars = sum(len(squash(" ".join(g))) for g in groups) or 1
        t, span = piece["start"], piece["end"] - piece["start"]
        for g in groups:
            share = span * len(squash(" ".join(g))) / total_chars
            chunks.append({"text": " ".join(g), "words": [], "start": t, "end": t + share})
            t += share
    for c in chunks:
        c["seg_id"] = piece["seg_id"]
    for a, b in zip(chunks, chunks[1:]):       # 한 문장 안의 조각은 잠깐 쉬어도 이어서 보여 준다
        if 0 < b["start"] - a["end"] < 1.0:
            a["end"] = b["start"]
    return chunks


def build_subtitle_events(keep: list[KeepRange], lines_by_clip: dict[str, list[Line]],
                          decisions: dict[str, LineDecision], style: StyleSpec, total: float) -> list[SubtitleEvent]:
    chunks: list[dict] = []
    for piece in _pieces(keep, lines_by_clip, decisions):
        chunks += _chunk(piece, style.max_chars_per_line)
    chunks.sort(key=lambda c: c["start"])
    events: list[SubtitleEvent] = []
    for i, c in enumerate(chunks):
        nxt = chunks[i + 1]["start"] if i + 1 < len(chunks) else total
        end = c["end"]
        if nxt - end < JOIN_GAP:
            end = nxt
        if end - c["start"] < MIN_SHOW:
            end = min(c["start"] + MIN_SHOW, nxt, total)
        end = min(end, nxt, total)
        if end - c["start"] < 0.05:
            continue
        word_lines = align_words_to_lines(c["text"], [w.word for w in c["words"]], style.max_chars_per_line) \
            if c["words"] else None
        events.append(SubtitleEvent(
            start=round(c["start"], 3), end=round(end, 3),
            text="\n".join(wrap_text(c["text"], style.max_chars_per_line)),
            style="subtitle", seg_id=c["seg_id"],
            words=c["words"] if word_lines else [], word_lines=word_lines or [],
        ))
    return events


GENERIC_PLACE = ("장소", "영상 전체", "장면 ")


def build_overlay_events(keep: list[KeepRange], tree: list[TreeNode], spans: list[ClipSpan],
                         styles: dict[str, StyleSpec], options: PlanOptions, total: float) -> list[SubtitleEvent]:
    """제목(처음 3초)과 촬영지 자막(장소가 바뀌는 곳)."""
    events: list[SubtitleEvent] = []
    title = options.title_text.strip()
    if title and total > 0:
        style = styles.get("title") or StyleSpec()
        events.append(SubtitleEvent(start=0.0, end=round(min(3.0, total), 3),
                                    text="\n".join(wrap_text(title, style.max_chars_per_line)), style="title"))
    if options.location_captions and tree:
        style = styles.get("location") or StyleSpec()
        last_end = -1.0
        for node in tree:
            name = node.title.strip()
            if not name or name.startswith(GENERIC_PLACE):
                continue
            first = None
            for clip_id, s, e in global_to_clip(node.start, node.end, spans):
                for k in keep:
                    if k.clip_id == clip_id and k.end > s and k.start < e:
                        t = k.out_start + (max(s, k.start) - k.start)
                        first = t if first is None else min(first, t)
            if first is None or first < last_end:
                continue
            end = min(first + 2.5, total)
            if end - first >= 0.5:
                events.append(SubtitleEvent(start=round(first, 3), end=round(end, 3),
                                            text="\n".join(wrap_text(name, style.max_chars_per_line)),
                                            style="location"))
                last_end = end
    return events
