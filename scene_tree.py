"""
영상분석(scene_analyzer) + 대사(받아쓰기) → 편집 설정 화면용 임시 4단 트리

4단 트리 설계(1-3)가 확정되기 전, 신정빈의 편집 설정 화면(장소/일/상황/대사 탭)을
실제 영상으로 테스트할 수 있게 코드로 단순하게 묶은 트리다.

    장소 (place가 같은 연속 장면)
     └ 일   (그 안에서 activity가 같은 연속 장면)
        └ 상황 (scene_analyzer 장면 하나)
           └ 대사 (받아쓰기 문장, 가운데 시각이 속한 장면에 넣음)

노드 형식은 prompt_builder.normalize_tree / 화면의 normalizeFakeTreeNode와 같다:
    {"id", "title", "start", "end", "summary"?, "tags"?, "children"}
부모 구간은 항상 자식 구간을 포함한다 (대사 시각은 속한 장면 범위로 자른다).
"""

import os
from pathlib import Path
from types import SimpleNamespace

# 조경우 scene_analyzer의 함수를 그대로 쓴다 (파일은 수정하지 않음)
from scene_analyzer import analyze_clip, clean_scenes, make_lowres, probe


def analyze_scenes(video_path: str, api_key: str, work_dir: str) -> list[dict]:
    """영상 하나를 scene_analyzer와 같은 방식으로 분석해 장면 목록(클립 기준 초)을 돌려준다."""
    from google import genai

    args = SimpleNamespace(
        model=os.getenv("SCENE_MODEL", "gemini-3.5-flash-lite"),
        mode="static", resolution="low", height=360,
        min_sec=float(os.getenv("SCENE_MIN_SEC", "10")), retries=2,
    )
    src = Path(video_path)
    duration = probe(src)["duration"]
    print(f"🎬 영상분석({args.model}) 시작: 저해상도 압축 → Gemini 업로드·분석")
    lowres = Path(work_dir) / f"{src.stem}_{args.height}p.mp4"
    make_lowres(src, lowres, args.height)
    raw, _usage = analyze_clip(genai.Client(api_key=api_key), lowres, duration, args, "", "")
    scenes = clean_scenes(raw, duration, args.min_sec)
    print(f"✅ 영상분석 완료: {len(scenes)}개 장면 ({', '.join(sc.get('place') or '?' for sc in scenes[:5])})")
    return scenes


def _short(text: str, n: int = 30) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _group(items: list, key) -> list[list]:
    """연속해서 key가 같은 것끼리 묶는다 (다시 나타나면 새 묶음 — 재방문은 새 노드)."""
    groups = []
    for it in items:
        if groups and key(groups[-1][-1]) == key(it):
            groups[-1].append(it)
        else:
            groups.append([it])
    return groups


def _line_nodes(segments: list[dict], lo: float, hi: float, prefix: str) -> list[dict]:
    nodes = []
    for i, s in enumerate(segments, 1):
        st, en = max(lo, float(s["start"])), min(hi, float(s["end"]))
        if en <= st:
            continue
        node = {"id": f"{prefix}-l{i:02d}", "title": _short(s.get("text", ""), 40), "start": round(st, 3),
                "end": round(en, 3), "summary": s.get("text", ""), "children": []}
        if s.get("cut"):
            node["tags"] = ["AI 컷 제안"]
        nodes.append(node)
    return nodes


def _span(children: list[dict]) -> tuple[float, float]:
    return min(c["start"] for c in children), max(c["end"] for c in children)


def build_tree(scenes: list[dict], segments: list[dict], duration: float) -> list[dict]:
    """장면 목록 + 대사 → 4단 트리. 장면 목록이 없으면 대사만으로 만든다 (영상분석 실패 대비)."""
    if not scenes:
        scenes = fallback_scenes(segments, duration)

    # 대사를 가운데 시각이 속한 장면에 배정
    lines_of = {id(sc): [] for sc in scenes}
    for s in segments:
        mid = (float(s["start"]) + float(s["end"])) / 2
        owner = next((sc for sc in scenes if sc["start"] <= mid < sc["end"]), scenes[-1])
        lines_of[id(owner)].append(s)

    tree = []
    for pi, place_group in enumerate(_group(scenes, lambda sc: sc.get("place", "")), 1):
        pid = f"p{pi:02d}"
        acts = []
        for ai, act_group in enumerate(_group(place_group, lambda sc: sc.get("activity", "")), 1):
            aid = f"{pid}-a{ai:02d}"
            sits = []
            for si, sc in enumerate(act_group, 1):
                sid = f"{aid}-s{si:02d}"
                node = {"id": sid, "title": _short(sc.get("event") or sc.get("summary") or "장면", 30),
                        "start": round(sc["start"], 3), "end": round(sc["end"], 3),
                        "summary": sc.get("summary", ""),
                        "children": _line_nodes(lines_of[id(sc)], sc["start"], sc["end"], sid)}
                tags = [t for t in (sc.get("mood"), sc.get("people")) if t]
                if tags:
                    node["tags"] = tags
                sits.append(node)
            st, en = _span(sits)
            acts.append({"id": aid, "title": act_group[0].get("activity") or "활동", "start": st, "end": en,
                         "children": sits})
        st, en = _span(acts)
        tree.append({"id": pid, "title": place_group[0].get("place") or "장소", "start": st, "end": en,
                     "children": acts})
    return tree


def fallback_scenes(segments: list[dict], duration: float, gap: float = 1.5) -> list[dict]:
    """영상분석 결과가 없을 때: 영상 전체를 장소 1개로 보고, 대사 사이 쉼(gap초 이상)으로 상황을 나눈다."""
    base = {"place": "영상 전체 (영상분석 없음)", "activity": "전체"}
    if not segments:
        return [{**base, "start": 0.0, "end": duration, "summary": "대사 없음"}]
    cuts = [0.0]
    for prev, cur in zip(segments, segments[1:]):
        if float(cur["start"]) - float(prev["end"]) >= gap:
            cuts.append((float(prev["end"]) + float(cur["start"])) / 2)
    cuts.append(max(duration, float(segments[-1]["end"])))
    scenes = []
    for st, en in zip(cuts, cuts[1:]):
        first = next((s for s in segments if st <= float(s["start"]) < en), None)
        scenes.append({**base, "start": st, "end": en, "summary": first["text"] if first else ""})
    return scenes
