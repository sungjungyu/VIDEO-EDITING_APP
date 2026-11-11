"""4단 트리 (S4 구조 편집): 분석 결과(Analysis) → analysis.tree.build_scene_tree 입력 → 트리.

요청할 때 만들고 프로젝트 폴더의 tree.json에 저장한다. 분석이 바뀌면(created_at·클립이 다르면) 다시 만든다.
지금은 AI 없이 규칙으로만 묶는다 (AI 구조화는 ask를 넘겨야 하고, 아직 쓰지 않는다).

입력 변환 (서버 → scene_tree)
    시각       서버는 '클립 안 초', scene_tree는 '전체 타임라인 초' → clip offset을 더한다
    장면       summary → desc, activity → action, people(글자) → 쉼표로 나눈 목록, place·event·mood 그대로
               visible_text(화면 글자)는 서버에 없어 비운다 (AI 대사 보정에서만 쓰인다)
    클립       created(세션 나누기용 촬영 시각)는 Analysis에 없어 프로젝트 클립의 created_at을 쓴다
"""

from __future__ import annotations

import hashlib
import json
import time

from ..analysis.tree import LEVEL_NAMES, build_scene_tree
from ..domain.models import Analysis, ClipInfo
from ..errors import NotFound
from ..storage.projects import ProjectStore

TREE_VERSION = 1          # 트리 만드는 규칙이나 출력 모양을 바꾸면 올린다 (저장해 둔 트리를 다시 만들게)
TREE_FILE = "tree.json"


def tree_inputs(analysis: Analysis, clips: list[ClipInfo]) -> tuple[list[dict], list[dict], list[dict]]:
    """Analysis → (clips, shots, segments) — scene_tree 입력 모양, 시각은 전체 타임라인 초."""
    info = {c.clip_id: c for c in clips}
    offset = {c.clip_id: c.offset for c in analysis.clips}
    tree_clips = [{"id": c.clip_id, "file": info[c.clip_id].filename if c.clip_id in info else "",
                   "duration": c.duration, "offset": c.offset,
                   "created": info[c.clip_id].created_at if c.clip_id in info else None}
                  for c in analysis.clips]
    shots = [{"clip_id": s.clip_id, "start": s.start + offset[s.clip_id], "end": s.end + offset[s.clip_id],
              "desc": s.summary, "place": s.place, "action": s.activity,
              "people": [p.strip() for p in s.people.split(",") if p.strip()],
              "event": s.event, "mood": s.mood}
             for s in analysis.scenes if s.clip_id in offset]
    segments = [{"seg_id": x.seg_id, "clip_id": x.clip_id, "start": x.start + offset[x.clip_id],
                 "end": x.end + offset[x.clip_id], "text": x.text, "speaker": x.speaker,
                 "words": [{"word": w.word, "start": w.start + offset[x.clip_id], "end": w.end + offset[x.clip_id]}
                           for w in x.words]}
                for x in analysis.lines if x.clip_id in offset]
    return tree_clips, shots, segments


def _slim(nodes: list[dict]) -> None:
    """화면에 보낼 때 L4 대사의 단어 시각은 뺀다 (1시간 영상이면 응답이 수 MB가 된다)."""
    for node in nodes:
        if node.get("level") == 4:
            node["lines"] = [{k: x[k] for k in ("id", "start", "end", "text", "speaker") if k in x}
                             for x in node.get("lines", [])]
        _slim(node.get("children", []))


def _count(nodes: list[dict], level: int) -> int:
    return sum((1 if n["level"] == level else 0) + _count(n.get("children", []), level) for n in nodes)


def build_tree_doc(analysis: Analysis, clips: list[ClipInfo]) -> dict:
    started = time.time()
    tree_clips, shots, segments = tree_inputs(analysis, clips)
    result = build_scene_tree(tree_clips, shots, segments)
    tree = result["tree"]
    _slim(tree)
    return {"meta": {"source": result["source"], "levels": list(LEVEL_NAMES), "version": TREE_VERSION,
                     "counts": {f"l{k}": _count(tree, k) for k in (1, 2, 3, 4)},
                     "elapsed_sec": round(time.time() - started, 2)},
            "clips": tree_clips, "tree": tree, "notes": result["notes"], "warnings": result["warnings"]}


def _key(analysis: Analysis, clips: list[dict]) -> str:
    raw = json.dumps([TREE_VERSION, analysis.created_at, clips], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get_tree(store: ProjectStore, project_id: str) -> dict:
    """저장해 둔 트리가 지금 분석과 맞으면 그대로, 아니면 새로 만들어 저장한다."""
    project = store.get(project_id)
    analysis = store.load_analysis(project_id)
    if analysis is None:
        raise NotFound("아직 분석하지 않았습니다.")
    key = _key(analysis, [[c.clip_id, c.offset, c.duration] for c in analysis.clips])
    path = store.project_dir(project_id) / TREE_FILE
    with store.lock(project_id):
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("key") == key:
                return {**saved["doc"], "cached": True}
        except (OSError, ValueError):
            pass
        doc = build_tree_doc(analysis, project.clips)
        path.write_text(json.dumps({"key": key, "doc": doc}, ensure_ascii=False), encoding="utf-8")
    return {**doc, "cached": False}
