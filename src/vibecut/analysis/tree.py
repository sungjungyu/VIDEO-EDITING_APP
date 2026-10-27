"""장면 + 대사 → 4단 트리 (장소 → 일 → 상황 → 대사). 묶는 규칙은 권용관이 만든 scene_tree에서 왔다.

    장소 (place가 같은 연속 장면)
     └ 일   (그 안에서 activity가 같은 연속 장면)
        └ 상황 (장면 하나)
           └ 대사 (받아쓰기 문장, 가운데 시각이 속한 장면에 넣음)

group_tree    dict 장면·대사 → dict 트리 {"id", "title", "start", "end", "summary"?, "tags"?, "seg_id"?, "children"}
              부모 구간은 항상 자식 구간을 포함한다 (대사 시각은 속한 장면 범위로 자른다)
build_tree    여러 클립을 '원본 초'(타임라인 순서로 이어 붙인 시각)로 펼쳐 group_tree로 묶고 TreeNode로 바꾼다
"""

from __future__ import annotations

from ..domain.models import ClipSpan, Line, LineDecision, Scene, TreeNode
from ..domain.timebase import fmt_clock


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
        if s.get("seg_id"):         # 받아쓰기 문장 id (vibecut 편집 계획이 대사 노드 ↔ 문장을 잇는 데 쓴다)
            node["seg_id"] = s["seg_id"]
        if s.get("cut"):
            node["tags"] = ["AI 컷 제안"]
        nodes.append(node)
    return nodes


def _span(children: list[dict]) -> tuple[float, float]:
    return min(c["start"] for c in children), max(c["end"] for c in children)


def group_tree(scenes: list[dict], segments: list[dict], duration: float) -> list[dict]:
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


# ---------------------------------------------------------------- 편집 계획용 TreeNode

def build_tree(spans: list[ClipSpan], scenes: list[Scene], lines: list[Line],
               decisions: dict[str, LineDecision], clip_labels: dict[str, str]) -> list[TreeNode]:
    offsets = {s.clip_id: s.offset for s in spans}
    total = sum(s.duration for s in spans)
    g_scenes = []
    for sc in sorted(scenes, key=lambda x: (offsets.get(x.clip_id, 0.0), x.start)):
        off = offsets.get(sc.clip_id)
        if off is None:
            continue
        local = sc.source == "local"
        g_scenes.append({
            "start": off + sc.start, "end": off + sc.end,
            "place": sc.place or clip_labels.get(sc.clip_id, sc.clip_id),
            "activity": sc.activity or ("전체" if local else ""),
            "event": sc.event, "mood": sc.mood, "people": sc.people,
            "summary": sc.summary or f"장면 {fmt_clock(sc.start)}~{fmt_clock(sc.end)}",
        })
    g_lines = []
    for line in sorted(lines, key=lambda x: (offsets.get(x.clip_id, 0.0), x.start)):
        off = offsets.get(line.clip_id)
        if off is None:
            continue
        d = decisions.get(line.seg_id)
        g_lines.append({"start": off + line.start, "end": off + line.end, "text": line.text or "(말소리)",
                        "seg_id": line.seg_id, "cut": bool(d and not d.keep)})
    raw = group_tree(g_scenes, g_lines, total)
    return [_node(n, 0) for n in raw]


def _node(raw: dict, level: int) -> TreeNode:
    return TreeNode(id=raw["id"], title=raw.get("title") or "", level=level, start=float(raw["start"]),
                    end=float(raw["end"]), summary=raw.get("summary") or "", tags=list(raw.get("tags") or []),
                    seg_id=raw.get("seg_id"), children=[_node(c, level + 1) for c in raw.get("children") or []])
