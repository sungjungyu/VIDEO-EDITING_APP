"""컷 판단 채점: 정답 vs 예측 → precision·recall·F1·이유별 recall·Gemini 비율."""

from __future__ import annotations

from vibecut.domain.models import GoldLabel, LineDecision
from vibecut.eval.bench import Pair, bootstrap_f1, pairs_for, score, to_markdown


def test_counts_cut_as_positive_and_missing_prediction_means_keep():
    gold = {"a": GoldLabel(keep=False, reason="NG"), "b": GoldLabel(keep=False, reason="군더더기"),
            "c": GoldLabel(keep=True), "d": GoldLabel(keep=True)}
    pred = {"a": LineDecision(seg_id="a", keep=False, reason="반복"),     # 이유가 달라도 자르면 맞음
            "c": LineDecision(seg_id="c", keep=False)}                    # 살려야 할 말을 자름
    s = score(pairs_for(["a", "b", "c", "d"], gold, pred, asked={"a", "b"}), ci_rounds=0)
    assert (s["tp"], s["fp"], s["fn"], s["tn"]) == (1, 1, 1, 1)           # b는 예측이 없어 '남김'
    assert s["precision"] == 0.5 and s["recall"] == 0.5 and s["f1"] == 0.5
    assert s["ai_ratio"] == 0.5
    assert s["by_reason"] == {"NG": {"gold": 1, "cut": 1, "recall": 1.0},
                              "군더더기": {"gold": 1, "cut": 0, "recall": 0.0}}


def test_no_cuts_at_all_gives_zero_f1_and_no_precision():
    s = score([Pair(True, "일반", True)] * 3, ci_rounds=0)
    assert s["f1"] == 0.0 and s["precision"] is None and s["recall"] is None and s["accuracy"] == 1.0


def test_bootstrap_interval_contains_point_estimate_and_is_reproducible():
    pairs = [Pair(False, "NG", False)] * 20 + [Pair(False, "NG", True)] * 5 + [Pair(True, "일반", False)] * 5 \
        + [Pair(True, "일반", True)] * 70
    s = score(pairs, ci_rounds=300)
    lo, hi = s["f1_ci95"]
    assert lo <= s["f1"] <= hi and hi - lo < 0.4
    assert bootstrap_f1(pairs, 300) == bootstrap_f1(pairs, 300)          # 같은 seed면 같은 구간


def test_markdown_table_lists_every_method_and_reason():
    s = score([Pair(False, "NG", False), Pair(True, "일반", True)], ci_rounds=0)
    text = to_markdown([{"method": "rule", "score": s, "seconds": 0.1}, {"method": "gemini", "score": s, "seconds": 2}])
    assert "| rule |" in text and "| gemini |" in text and "NG (n=1)" in text
