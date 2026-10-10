"""
받아쓰기 엔진 비교표 만들기 (작업계획서 Step 3)

같은 클립 폴더를 엔진별로 transcriber.py로 돌린 결과(transcript.json)들을 받아 표 하나로 비교한다.

사용 예:
    python stt_compare.py whisper.json gemini.json --ref ref.json --truth truth.json --out docs/stt_비교.md

--ref (선택): 직접 받아쓴 정답. 클립 파일명 → 정답 문장. 일부 구간만 받아썼으면 클립 안 초로 범위를 준다.
    {"a.mp4": "안녕하세요 오늘은 …", "b.mp4": {"text": "…", "start": 0, "end": 120}}
    정답이 빈 문자열이면 '말소리 없음' 클립으로 보고 엔진이 출력한 글자 수를 센다 (환각 확인용).
--truth (선택): 실제 말소리 구간 (클립 안 초). 문장 시작·끝 시각 오차를 잰다.
    {"a.mp4": [[1.12, 1.97], [2.84, 5.68]]}
"""

import argparse
import json
import re
from pathlib import Path


def squash(text: str) -> str:
    """글자 오류율은 띄어쓰기·문장부호를 빼고 글자만 비교한다."""
    return re.sub(r"[\W_]+", "", text)


def edit_distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def clip_words(t: dict, clip_file: str) -> tuple[list[dict], float]:
    """그 클립의 단어들 (클립 안 초)과 클립 offset."""
    clip = next((c for c in t["clips"] if c["file"] == clip_file), None)
    if clip is None:
        return [], 0.0
    words = []
    for s in t["segments"]:
        if s["clip_id"] != clip["id"]:
            continue
        off = s["start"] - s["clip_start"]
        words += [{**w, "start": w["start"] - off, "end": w["end"] - off} for w in s["words"]]
    return words, clip["offset"]


def hyp_text(t: dict, clip_file: str, start: float | None, end: float | None) -> str:
    words, _ = clip_words(t, clip_file)
    if start is not None:
        words = [w for w in words if start - 0.5 <= w["start"] and w["end"] <= end + 0.5]
    return "".join(w["word"] for w in words)


def score_ref(t: dict, refs: dict) -> dict:
    edits = chars = silent_out = 0
    per_clip = {}
    for clip_file, ref in refs.items():
        if isinstance(ref, str):
            ref = {"text": ref}
        hyp = squash(hyp_text(t, clip_file, ref.get("start"), ref.get("end")))
        r = squash(ref["text"])
        if not r:
            silent_out += len(hyp)
            per_clip[clip_file] = f"말소리 없음, 출력 {len(hyp)}자"
            continue
        e = edit_distance(r, hyp)
        edits, chars = edits + e, chars + len(r)
        per_clip[clip_file] = f"{e / len(r) * 100:.1f}%"
    return {"cer": edits / chars if chars else None, "silent_out": silent_out, "per_clip": per_clip}


def score_truth(t: dict, truth: dict) -> dict:
    errs = []
    for clip_file, spans in truth.items():
        words, _ = clip_words(t, clip_file)
        if not words:
            continue
        for s, e in spans:
            errs.append(min(abs(w["start"] - s) for w in words))
            errs.append(min(abs(w["end"] - e) for w in words))
    return {"mean": sum(errs) / len(errs), "max": max(errs)} if errs else {}


def main():
    ap = argparse.ArgumentParser(description="받아쓰기 엔진 비교표")
    ap.add_argument("transcripts", nargs="+", help="엔진별 transcript.json")
    ap.add_argument("--ref", help="정답 받아쓰기 JSON")
    ap.add_argument("--truth", help="실제 말소리 구간 JSON")
    ap.add_argument("--out", help="표를 저장할 md 파일")
    args = ap.parse_args()

    refs = json.loads(Path(args.ref).read_text(encoding="utf-8")) if args.ref else None
    truth = json.loads(Path(args.truth).read_text(encoding="utf-8")) if args.truth else None

    head = ["엔진", "모델", "무음 보정", "오디오", "처리 시간", "배속", "문장", "단어", "환각 제외", "검증 경고", "토큰"]
    if refs:
        head += ["글자 오류율", "말소리 없는 클립 출력"]
    if truth:
        head += ["문장 경계 오차 (평균/최대)"]
    rows, details = [], []
    for path in args.transcripts:
        t = json.loads(Path(path).read_text(encoding="utf-8"))
        m = t["meta"]
        audio = sum(c["duration"] for c in t["clips"] if c.get("has_audio"))
        sec = m.get("engine_sec")
        usage = m.get("usage") or {}
        row = [m["engine"], m["model"], "켬" if m.get("refine") else "끔", f"{audio:.0f}초",
               f"{sec:.1f}초" if sec is not None else "기록 없음",
               f"{sec / audio:.2f}배" if sec is not None and audio else "-",
               str(len(t["segments"])), str(sum(len(s["words"]) for s in t["segments"])),
               str(len(t.get("dropped", []))), str(len(t.get("warnings", []))),
               str(usage.get("total_tokens", "-"))]
        if refs:
            r = score_ref(t, refs)
            row += [f"{r['cer'] * 100:.1f}%" if r["cer"] is not None else "-", f"{r['silent_out']}자"]
            details.append(f"- {m['engine']} ({m['model']}, 보정 {'켬' if m.get('refine') else '끔'}): " + ", ".join(f"{k} {v}" for k, v in r["per_clip"].items()))
        if truth:
            b = score_truth(t, truth)
            row += [f"{b['mean']:.2f}초 / {b['max']:.2f}초" if b else "-"]
        rows.append(row)

    lines = ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)] + ["| " + " | ".join(r) + " |" for r in rows]
    if details:
        lines += ["", "클립별 글자 오류율:", ""] + details
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
