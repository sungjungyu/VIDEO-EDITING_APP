"""4단 트리 (S4 구조 편집): 분석 결과(Analysis) → analysis.tree.build_scene_tree 입력 → 트리.

요청할 때 만들고 프로젝트 폴더에 저장한다(규칙 트리 tree_rules.json, AI 트리 tree_ai.json).
분석이 바뀌면(created_at·클립이 다르면) 다시 만든다.

    규칙 트리   AI 없이 build_units + fallback_structure (빠름, 무료)
    AI 트리     서버 GeminiClient.generate_json으로 대사 보정 + L1~L3 경계·제목 (429 재시도·대체 모델·사용량 기록·
                AI 응답 캐시를 그대로 쓴다). AI가 실패한 조각은 scene_tree가 규칙으로 묶고 경고를 남긴다
    GET /tree   AI 트리가 저장돼 있으면 그것, 없으면 규칙 트리 (화면이 오래 기다리지 않게). ?ai=true면 AI 트리를 만든다

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

from ..ai.client import GeminiClient, Usage
from ..analysis.tree import LEVEL_NAMES, build_scene_tree
from ..domain.models import Analysis, ClipInfo
from ..errors import NotFound
from ..storage.projects import ProjectStore

TREE_VERSION = 3          # 트리 만드는 규칙이나 출력 모양을 바꾸면 올린다 (저장해 둔 트리를 다시 만들게)
TREE_FILES = {"rules": "tree_rules.json", "ai": "tree_ai.json"}
TREE_MAX_OUTPUT_TOKENS = 16384   # 20분 조각 하나의 응답(보정 + 세션·흐름·단계 목록)


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


def ai_ask(client: GeminiClient):
    """scene_tree의 ask(prompt, schema) → dict 를 서버 AI 클라이언트로 (자체 Gemini 호출을 만들지 않는다)."""
    def ask(prompt: str, schema: dict) -> dict:
        return client.generate_json(prompt, schema, purpose="트리 구조화", temperature=0.2,
                                    max_output_tokens=TREE_MAX_OUTPUT_TOKENS)
    return ask


def build_tree_doc(analysis: Analysis, clips: list[ClipInfo], client: GeminiClient | None = None) -> dict:
    """client를 주면 AI 트리, 없으면 규칙 트리. AI 사용량(요청·토큰·캐시 적중)은 meta.ai_usage에 남긴다."""
    started = time.time()
    tree_clips, shots, segments = tree_inputs(analysis, clips)
    usage = Usage()
    ask = ai_ask(client.with_usage(usage)) if client is not None else None
    result = build_scene_tree(tree_clips, shots, segments, ask=ask)
    tree = result["tree"]
    _slim(tree)
    meta = {"source": result["source"], "levels": list(LEVEL_NAMES), "version": TREE_VERSION,
            "counts": {f"l{k}": _count(tree, k) for k in (1, 2, 3, 4)},
            "elapsed_sec": round(time.time() - started, 2)}
    if client is not None:
        meta["ai_usage"] = usage.to_dict()
        meta["corrections"] = len(result["corrections"])
    return {"meta": meta, "clips": tree_clips, "tree": tree, "notes": result["notes"], "warnings": result["warnings"]}


def _key(analysis: Analysis, clips: list[dict]) -> str:
    raw = json.dumps([TREE_VERSION, analysis.created_at, clips], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _load(path, key: str) -> dict | None:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return saved["doc"] if saved.get("key") == key else None


def get_tree(store: ProjectStore, project_id: str, client: GeminiClient | None = None, ai: bool = False) -> dict:
    """ai=False: 저장된 AI 트리가 있으면 그것, 없으면 규칙 트리(없으면 만든다).
    ai=True: AI 트리 (저장된 것이 없으면 client로 만든다. 몇 분 걸릴 수 있다)."""
    project = store.get(project_id)
    analysis = store.load_analysis(project_id)
    if analysis is None:
        raise NotFound("아직 분석하지 않았습니다.")
    key = _key(analysis, [[c.clip_id, c.offset, c.duration] for c in analysis.clips])
    paths = {kind: store.project_dir(project_id) / name for kind, name in TREE_FILES.items()}
    with store.lock(project_id):
        saved_ai = _load(paths["ai"], key)
        if saved_ai is not None:
            return {**saved_ai, "cached": True}
        if not ai:
            saved = _load(paths["rules"], key)
            if saved is not None:
                return {**saved, "cached": True}
    kind = "ai" if ai and client is not None else "rules"
    doc = build_tree_doc(analysis, project.clips, client if kind == "ai" else None)   # AI 호출 동안 잠그지 않는다
    if kind == "ai" and doc["meta"]["source"] == "rules":
        kind = "rules"            # AI가 모두 실패해 규칙으로 돌아감: AI 트리로 저장하지 않는다 (다음에 다시 시도)
    with store.lock(project_id):
        paths[kind].write_text(json.dumps({"key": key, "doc": doc}, ensure_ascii=False), encoding="utf-8")
    return {**doc, "cached": False}
