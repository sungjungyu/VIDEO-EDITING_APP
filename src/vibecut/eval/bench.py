"""컷 판단 채점 (v4 설계안 T1): 판단 결과를 사람이 검수한 정답과 비교한다.

'자름'을 양성으로 본다.
    precision  자르라고 한 것 중 정답도 자름인 비율 (살려야 할 말을 잘못 자르지 않는가)
    recall     정답이 자름인 것 중 실제로 자른 비율 (빼야 할 말을 놓치지 않는가)
    F1         둘의 조화 평균
    이유별 recall  정답 이유(NG·반복·군더더기·지시어·직접)마다 몇 개를 잘랐나 (이유는 달라도 자르면 맞음)

F1의 95% 구간은 문장을 복원 추출해 다시 계산하는 부트스트랩으로 구한다 — 문장 수가 적으면 구간이 넓다.
여러 정답 묶음은 문장을 모두 합쳐(micro) 계산한다.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass

from ..domain.models import GoldLabel, LineDecision


@dataclass(frozen=True)
class Pair:
    """문장 하나의 (정답, 예측)."""
    gold_keep: bool
    gold_reason: str
    pred_keep: bool
    asked_ai: bool = False


def pairs_for(ids: Iterable[str], gold: dict[str, GoldLabel], pred: dict[str, LineDecision],
              asked: set[str] | None = None) -> list[Pair]:
    """예측이 없는 문장은 '남김'으로 본다 (엔진이 판단을 돌려주지 않으면 남기는 것과 같다)."""
    asked = asked or set()
    out = []
    for sid in ids:
        g = gold[sid]
        d = pred.get(sid)
        out.append(Pair(g.keep, g.reason, True if d is None else d.keep, sid in asked))
    return out


def _f1(tp: int, fp: int, fn: int) -> float:
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def _counts(pairs: list[Pair]) -> tuple[int, int, int, int]:
    tp = sum(1 for p in pairs if not p.gold_keep and not p.pred_keep)
    fp = sum(1 for p in pairs if p.gold_keep and not p.pred_keep)
    fn = sum(1 for p in pairs if not p.gold_keep and p.pred_keep)
    tn = len(pairs) - tp - fp - fn
    return tp, fp, fn, tn


def bootstrap_f1(pairs: list[Pair], rounds: int = 1000, seed: int = 0) -> tuple[float, float] | None:
    if len(pairs) < 2:
        return None
    rng = random.Random(seed)
    n = len(pairs)
    values = []
    for _ in range(rounds):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        tp, fp, fn, _tn = _counts(sample)
        values.append(_f1(tp, fp, fn))
    values.sort()
    return round(values[int(0.025 * rounds)], 3), round(values[int(0.975 * rounds) - 1], 3)


def score(pairs: list[Pair], ci_rounds: int = 1000) -> dict:
    tp, fp, fn, tn = _counts(pairs)
    n = len(pairs)
    reasons: dict[str, dict] = {}
    for p in pairs:
        if p.gold_keep:
            continue
        r = reasons.setdefault(p.gold_reason, {"gold": 0, "cut": 0})
        r["gold"] += 1
        r["cut"] += 0 if p.pred_keep else 1
    for r in reasons.values():
        r["recall"] = round(r["cut"] / r["gold"], 3)
    return {
        "sentences": n,
        "gold_cut": tp + fn,
        "pred_cut": tp + fp,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "f1": round(_f1(tp, fp, fn), 3),
        "f1_ci95": bootstrap_f1(pairs, ci_rounds) if ci_rounds else None,
        "accuracy": round((tp + tn) / n, 3) if n else None,
        "ai_ratio": round(sum(p.asked_ai for p in pairs) / n, 3) if n else 0.0,
        "by_reason": dict(sorted(reasons.items())),
    }


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def to_markdown(rows: list[dict], title: str = "컷 판단 평가") -> str:
    """rows: [{"method", "score", "seconds"}] → 발표·보고서용 표."""
    out = [f"## {title}", "",
           "| 방법 | 문장 | 정답 자름 | F1 (95% 구간) | precision | recall | Gemini에 보낸 문장 | 시간 |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        s = row["score"]
        ci = f" ({s['f1_ci95'][0]:.2f}~{s['f1_ci95'][1]:.2f})" if s.get("f1_ci95") else ""
        out.append(f"| {row['method']} | {s['sentences']} | {s['gold_cut']} | {s['f1']:.2f}{ci} | "
                   f"{_num(s['precision'])} | {_num(s['recall'])} | {s['ai_ratio'] * 100:.0f}% | "
                   f"{row['seconds']:.1f}초 |")
    reasons = sorted({r for row in rows for r in row["score"]["by_reason"]})
    if reasons:
        out += ["", "이유별 recall (정답 이유 기준, 자르기만 하면 맞음)", "",
                "| 방법 | " + " | ".join(f"{r} (n={rows[0]['score']['by_reason'].get(r, {}).get('gold', 0)})"
                                        for r in reasons) + " |",
                "| --- |" + " --- |" * len(reasons)]
        for row in rows:
            by = row["score"]["by_reason"]
            out.append(f"| {row['method']} | " + " | ".join(f"{by[r]['recall']:.2f}" if r in by else "-"
                                                          for r in reasons) + " |")
    return "\n".join(out)
