"""AI 가편집: 장면 점수(LLM 또는 규칙) + 목표 분량 맞추기(코드).

예전 scene_selector는 Gemini에게 분량 합산까지 맡기고 ±10% 검사에 걸리면 한 번 더 물었다.
여기서는 Gemini가 '얼마나 좋은 장면인가(score)·꼭 넣기(must)·빼기(never)·이유'만 정하고,
분량은 코드가 맞춘다 → 목표 ±5%를 구조적으로 맞추고, 재요청이 필요 없다.

분량 맞추기 (fit_duration)
    1. 사용자가 고정한 장면 + must
    2. 남은 장면을 점수 높은 순으로, 목표의 +5%를 넘지 않게 통째로 넣는다
    3. 그래도 -5%에 못 미치면, 넣지 못한 장면의 대사 중 좋은 것부터 한 문장씩 채운다
    각 장면의 길이는 '실제로 남는 길이'(자를 문장·긴 쉼을 뺀 길이)로 계산한다 (planner와 같은 계산)
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from ..edit.planner import flatten, plan_clip
from ..edit.timeline import global_to_clip
from ..models import Analysis, ClipInfo, EditPlan, LineDecision, Selection, TreeNode
from .gemini import AIError, AIUnavailable, GeminiClient

log = logging.getLogger("vibecut.ai.select")

TOLERANCE = 0.05
_STOP = {"장면", "위주", "위주로", "영상", "부분", "해줘", "빼줘", "만들어", "만들어줘", "주세요", "그리고", "쇼츠",
         "쇼츠용", "재밌는", "재미있는", "좋은", "편집", "편집해줘", "분량", "정도", "넣어줘", "나오는"}


def candidate_nodes(tree: list[TreeNode]) -> list[TreeNode]:
    """점수를 매길 단위: '상황'(level 2). 트리가 얕으면 있는 가장 깊은 단계(대사 제외)."""
    nodes = list(flatten(tree).values())
    for level in (2, 1, 0):
        found = [n for n in nodes if n.level == level]
        if found:
            return sorted(found, key=lambda n: n.start)
    return []


def effective_seconds(node: TreeNode, analysis: Analysis, clips: dict[str, ClipInfo],
                      decisions: dict[str, LineDecision], plan: EditPlan) -> float:
    """이 장면만 골랐을 때 실제로 남는 길이 (planner와 같은 계산)."""
    total = 0.0
    lines_by_clip = analysis.lines_by_clip()
    for clip_id, s, e in global_to_clip(node.start, node.end, analysis.clips):
        clip = clips.get(clip_id)
        if clip is None:
            continue
        silences = [tuple(x) for x in analysis.silences.get(clip_id, [])]
        kept = plan_clip(clip, [(s, e)], lines_by_clip.get(clip_id, []), decisions, {}, silences, plan.options)
        total += sum(b - a for a, b in kept)
    return total


def _keywords(prompt: str) -> tuple[list[str], list[str]]:
    """사용자 요청 → (넣고 싶은 말, 빼고 싶은 말). '…는 빼줘', '…없이' 앞의 낱말은 빼고 싶은 말."""
    want, avoid = [], []
    for clause in re.split(r"[,.\n]| 그리고 ", prompt or ""):
        words = [w.strip("은는이가을를도만의에서로요 ") for w in clause.split()]
        words = [w for w in words if len(w) >= 2 and w not in _STOP]
        negative = re.search(r"(빼|제외|없이|말고|싫)", clause)
        (avoid if negative else want).extend(w for w in words if not re.search(r"(빼|제외|없이|말고|싫)", w))
    return want, avoid


def heuristic_scores(nodes: list[TreeNode], analysis: Analysis, decisions: dict[str, LineDecision],
                     prompt: str) -> dict[str, dict]:
    want, avoid = _keywords(prompt)
    lines = {line.seg_id: line for line in analysis.lines}
    out = {}
    for i, node in enumerate(nodes):
        dur = max(0.1, node.end - node.start)
        seg_ids = [n.seg_id for n in flatten([node]).values() if n.seg_id]
        kept = [lines[s] for s in seg_ids if s in lines and (decisions.get(s) is None or decisions[s].keep)]
        speech = sum(line.end - line.start for line in kept) / dur
        emphasis = any(decisions.get(s) and decisions[s].emphasis for s in seg_ids)
        text = " ".join([node.title, node.summary] + [line.text for line in kept])
        hit = [w for w in want if w in text]
        miss = [w for w in avoid if w in text]
        score = 0.35 + 0.25 * min(1.0, speech * 1.5) + (0.15 if emphasis else 0.0)
        score += 0.3 * (len(hit) / len(want)) if want else 0.0
        score += 0.05 if i in (0, len(nodes) - 1) else 0.0
        reasons = []
        if hit:
            reasons.append(f"요청 단어 포함: {', '.join(hit[:3])}")
        if emphasis:
            reasons.append("강조할 말이 있음")
        if speech > 0.5:
            reasons.append("말이 많은 장면")
        elif speech < 0.1:
            reasons.append("말 없는 장면")
        reason = f"요청에서 뺀 내용: {', '.join(miss[:3])}" if miss else ("; ".join(reasons) or "기본 점수")
        out[node.id] = {"score": round(max(0.0, min(1.0, score)), 3), "must": False, "never": bool(miss),
                        "reason": reason}
    return out


class ScoreItem(BaseModel):
    id: str
    score: float
    must: bool
    never: bool
    reason: str


class ScoreResponse(BaseModel):
    scores: list[ScoreItem]


def build_prompt(nodes: list[TreeNode], analysis: Analysis, decisions: dict[str, LineDecision], prompt: str,
                 target_sec: float, profile: dict) -> str:
    lines = {line.seg_id: line for line in analysis.lines}
    total = sum(s.duration for s in analysis.clips)
    rows = []
    for node in nodes:
        texts = [lines[n.seg_id].text for n in flatten([node]).values()
                 if n.seg_id in lines and (decisions.get(n.seg_id) is None or decisions[n.seg_id].keep)][:3]
        rows.append(f"{node.id} | {node.start:.0f}~{node.end:.0f}s | {node.title[:30]} | {node.summary[:60]} | "
                    f"{' / '.join(t[:40] for t in texts) or '(말 없음)'}")
    tempo = profile.get("cut_tempo") or "(선택 없음)"
    return f"""당신은 영상 편집자다. 아래 장면 목록을 보고 결과 영상에 넣을 가치를 장면마다 점수로 매겨라.

[사용자 요청] {prompt.strip() or "(없음 — 재미·정보·감정이 큰 장면 위주)"}
[목표 분량] {target_sec:.0f}초 (원본 {total:.0f}초)  ※ 분량 계산은 하지 마라. 고르는 것은 프로그램이 한다.
[제작자 컷 템포] {tempo}
[규칙]
- score(0~1): 높을수록 넣을 가치가 크다. 요청에 맞는 장면, 처음 시작·마무리 장면, 사건이 있는 장면을 높게.
- must: 요청상 꼭 넣어야 하는 장면만 true.
- never: 요청에서 빼 달라고 한 내용(사람·장소·주제)이 있는 장면만 true.
- reason: 20자 이내 한국어 한 줄.
- 모든 장면 id를 빠짐없이 돌려준다.

[장면 목록] id | 원본 시각 | 제목 | 요약 | 주요 대사
{chr(10).join(rows)}
"""


def fit_duration(nodes: list[TreeNode], seconds: dict[str, float], scores: dict[str, dict], locked: list[str],
                 target: float, line_seconds: dict[str, float], line_scores: dict[str, float]) -> list[str]:
    """목표 분량에 맞게 고른 노드 id (장면 통째 + 모자라면 대사 단위). 원본 시각 순서."""
    hi, lo = target * (1 + TOLERANCE), target * (1 - TOLERANCE)
    chosen: list[str] = []
    total = 0.0
    for node in nodes:
        if node.id in locked or scores.get(node.id, {}).get("must"):
            chosen.append(node.id)
            total += seconds.get(node.id, 0.0)
    rest = [n for n in nodes if n.id not in chosen and not scores.get(n.id, {}).get("never")]
    rest.sort(key=lambda n: (-scores.get(n.id, {}).get("score", 0.0), n.start))
    for node in rest:
        if total >= lo:
            break
        sec = seconds.get(node.id, 0.0)
        if sec > 0 and total + sec <= hi:
            chosen.append(node.id)
            total += sec
    if total < lo:                 # 모자람 → 못 넣은 장면에서 좋은 대사만
        for node in rest:
            if node.id in chosen:
                continue
            children = [c for c in flatten([node]).values() if c.seg_id and c.seg_id in line_seconds]
            children.sort(key=lambda c: (-line_scores.get(c.seg_id, 0.0), c.start))
            for child in children:
                sec = line_seconds[child.seg_id]
                if sec > 0 and total + sec <= hi:
                    chosen.append(child.id)
                    total += sec
                if total >= lo:
                    break
            if total >= lo:
                break
    # 그래도 범위 밖이면(남은 조각이 모두 커서) 목표에 더 가까워지는 조각을 하나씩 더한다
    while total < lo:
        options = [(seconds.get(n.id, 0.0), n.id) for n in rest if n.id not in chosen]
        options += [(line_seconds[c.seg_id], c.id) for n in rest if n.id not in chosen
                    for c in flatten([n]).values() if c.seg_id in line_seconds and c.id not in chosen]
        options = [(sec, nid) for sec, nid in options if sec > 0]
        if not options:
            break
        sec, nid = min(options, key=lambda o: abs(total + o[0] - target))
        if abs(total + sec - target) >= abs(total - target):
            break
        chosen.append(nid)
        total += sec
    return chosen


def select_scenes(analysis: Analysis, clips: dict[str, ClipInfo], plan: EditPlan, decisions: dict[str, LineDecision],
                  target_sec: float, user_prompt: str, locked: list[str], profile: dict | None,
                  client: GeminiClient | None) -> tuple[Selection, str, list[str]]:
    """(선택 결과, 엔진, 경고)."""
    profile = profile or {}
    nodes = candidate_nodes(analysis.tree)
    warnings: list[str] = []
    if not nodes:
        return Selection(mode="all"), "rule", ["장면 트리가 없어 전체를 사용합니다. 먼저 분석하세요."]
    scores = heuristic_scores(nodes, analysis, decisions, user_prompt)
    engine = "rule"
    if client is not None:
        try:
            data = client.generate_json(build_prompt(nodes, analysis, decisions, user_prompt, target_sec, profile),
                                        ScoreResponse, purpose="장면 점수", temperature=0.2)
            ids = {n.id for n in nodes}
            for item in data.get("scores", []):
                if item["id"] in ids:
                    scores[item["id"]] = {"score": max(0.0, min(1.0, float(item["score"]))), "must": bool(item["must"]),
                                          "never": bool(item["never"]), "reason": str(item["reason"])[:60]}
            engine = "ai"
        except AIUnavailable:
            pass
        except AIError as error:
            warnings.append(f"AI 장면 점수 실패 → 규칙 점수로 골랐습니다: {str(error)[:150]}")
    all_nodes = flatten(analysis.tree)
    locked = [i for i in locked if i in all_nodes]
    seconds = {n.id: effective_seconds(n, analysis, clips, decisions, plan) for n in nodes}
    for lid in locked:
        if lid not in seconds:
            seconds[lid] = effective_seconds(all_nodes[lid], analysis, clips, decisions, plan)
    # 대사 하나를 넣으면 늘어나는 길이 ≈ 문장 길이 + 앞뒤 여유 (자를 문장이면 0)
    pad = plan.options.pad_start + plan.options.pad_end
    line_seconds, line_scores = {}, {}
    for line in analysis.lines:
        d = decisions.get(line.seg_id)
        line_seconds[line.seg_id] = 0.0 if d is not None and not d.keep else line.end - line.start + pad
        line_scores[line.seg_id] = 0.7 if d is not None and d.emphasis else 0.5
    candidates = nodes + [all_nodes[i] for i in locked if i not in {n.id for n in nodes}]
    chosen = fit_duration(candidates, seconds, scores, locked, target_sec, line_seconds, line_scores)
    locked_total = sum(seconds.get(i, 0.0) for i in locked)
    if locked_total > target_sec * (1 + TOLERANCE):
        warnings.append("고정한 장면만으로 목표 분량을 넘습니다.")
    available = sum(seconds.values())
    if available < target_sec * (1 - TOLERANCE):
        warnings.append(f"쓸 수 있는 분량({available:.0f}초)이 목표({target_sec:.0f}초)보다 짧습니다.")
    chosen.sort(key=lambda i: all_nodes[i].start)
    reasons = {i: scores[i]["reason"] for i in chosen if i in scores}
    selection = Selection(mode="auto", node_ids=chosen, target_sec=target_sec, user_prompt=user_prompt,
                          locked_ids=locked, reasons=reasons,
                          scores={i: v["score"] for i, v in scores.items()}, ai_node_ids=list(chosen))
    return selection, engine, warnings
