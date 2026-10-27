"""자연어 수정 요청 ("말더듬 다 잘라줘", "3번째 문장 살려줘").

예전 /revise는 세그먼트 배열을 통째로 돌려받아 시각·개수가 바뀌어도 그대로 썼다.
여기서는 문장 id별 변경(keep, text)만 받고, 모르는 id·지나치게 바뀐 글자는 버린다.
Gemini를 못 쓰면 자주 쓰는 명령(군더더기 제거, 전체 살리기)만 규칙으로 처리한다.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from ..models import Line, LineDecision
from .gemini import AIError, AIUnavailable, GeminiClient
from .judge import rule_decisions


class ReviseChange(BaseModel):
    id: str
    keep: bool | None = None
    text: str | None = None


class ReviseResponse(BaseModel):
    message: str
    changes: list[ReviseChange]


def _build_prompt(instruction: str, lines: list[Line], decisions: dict[str, LineDecision]) -> str:
    rows = []
    for line in lines:
        d = decisions.get(line.seg_id)
        keep = "남김" if d is None or d.keep else f"자름({d.reason})"
        text = d.text if d is not None and d.text else line.text
        rows.append(f"{line.seg_id} | {line.start:.1f}s | {keep} | {text}")
    return f"""당신은 영상 편집 도우미다. 사용자의 수정 요청을 문장 목록에 적용하라.

[요청] {instruction}

[규칙]
- 바꿀 문장만 changes에 넣는다. 각 항목: id, keep(남기면 true, 자르면 false, 그대로면 생략), text(자막 글자를 고칠 때만)
- 시각·순서는 바꿀 수 없다. 문장을 새로 만들거나 합치지 않는다.
- message: 무엇을 바꿨는지 한국어 한두 문장.

[문장 목록] id | 시작 | 현재 상태 | 자막
{chr(10).join(rows)}
"""


def _offline(instruction: str, lines: list[Line], decisions: dict[str, LineDecision], profile: dict
             ) -> tuple[dict[str, dict], str]:
    text = instruction.replace(" ", "")
    if re.search(r"(전체|모두|다)(살려|남겨)|자르지마", text):
        changes = {line.seg_id: {"keep": True} for line in lines
                   if decisions.get(line.seg_id) is not None and not decisions[line.seg_id].keep}
        return changes, f"잘려 있던 {len(changes)}개 문장을 모두 살렸습니다."
    if re.search(r"(말더듬|군더더기|군말|추임새|침묵|불필요|반복|컷편집|NG|엔지)", text, re.IGNORECASE):
        rules = rule_decisions(lines, {**profile, "filler_removal": "강"})
        changes = {sid: {"keep": False} for sid, d in rules.items()
                   if not d.keep and (decisions.get(sid) is None or decisions[sid].keep)}
        return changes, f"규칙으로 군더더기·NG·지시어 {len(changes)}개 문장을 잘랐습니다."
    return {}, "오프라인 모드에서는 '군더더기 제거', '전체 살리기' 같은 기본 명령만 처리할 수 있습니다."


def revise(instruction: str, lines: list[Line], decisions: dict[str, LineDecision], profile: dict | None,
           client: GeminiClient | None) -> tuple[dict[str, dict], str, str]:
    """(id → {"keep"?, "text"?}, 안내 메시지, 엔진)."""
    profile = profile or {}
    lines = sorted(lines, key=lambda x: x.seg_id)
    if client is not None:
        try:
            data = client.generate_json(_build_prompt(instruction, lines, decisions), ReviseResponse,
                                        purpose="수정 요청", temperature=0.2)
        except AIUnavailable:
            changes, message = _offline(instruction, lines, decisions, profile)
            return changes, message, "rule"
        except AIError as error:
            changes, message = _offline(instruction, lines, decisions, profile)
            return changes, f"AI 수정 실패 ({str(error)[:80]}) → {message}", "rule"
        by_id = {line.seg_id: line for line in lines}
        changes: dict[str, dict] = {}
        for item in data.get("changes", []):
            line = by_id.get(item["id"])
            if line is None:
                continue
            change = {}
            if item.get("keep") is not None:
                change["keep"] = bool(item["keep"])
            new_text = (item.get("text") or "").strip()
            if new_text and new_text != line.text and len(new_text) <= 2 * len(line.text) + 20:
                change["text"] = new_text
            if change:
                changes[line.seg_id] = change
        return changes, str(data.get("message") or "수정했습니다.")[:300], "ai"
    changes, message = _offline(instruction, lines, decisions, profile)
    return changes, message, "rule"
