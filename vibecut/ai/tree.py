"""장면 + 대사 → 4단 트리 (장소 → 일 → 상황 → 대사). 묶는 규칙은 scene_tree.py(권용관)를 그대로 쓴다.
여러 클립을 '원본 초'(타임라인 순서로 이어 붙인 시각)로 펼쳐서 한 번에 묶는다."""

from __future__ import annotations

from ..models import ClipSpan, Line, LineDecision, Scene, TreeNode


def _fmt(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def build_tree(spans: list[ClipSpan], scenes: list[Scene], lines: list[Line],
               decisions: dict[str, LineDecision], clip_labels: dict[str, str]) -> list[TreeNode]:
    import scene_tree

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
            "summary": sc.summary or f"장면 {_fmt(sc.start)}~{_fmt(sc.end)}",
        })
    g_lines = []
    for line in sorted(lines, key=lambda x: (offsets.get(x.clip_id, 0.0), x.start)):
        off = offsets.get(line.clip_id)
        if off is None:
            continue
        d = decisions.get(line.seg_id)
        g_lines.append({"start": off + line.start, "end": off + line.end, "text": line.text or "(말소리)",
                        "seg_id": line.seg_id, "cut": bool(d and not d.keep)})
    raw = scene_tree.build_tree(g_scenes, g_lines, total)
    return [_node(n, 0) for n in raw]


def _node(raw: dict, level: int) -> TreeNode:
    return TreeNode(id=raw["id"], title=raw.get("title") or "", level=level, start=float(raw["start"]),
                    end=float(raw["end"]), summary=raw.get("summary") or "", tags=list(raw.get("tags") or []),
                    seg_id=raw.get("seg_id"), children=[_node(c, level + 1) for c in raw.get("children") or []])
