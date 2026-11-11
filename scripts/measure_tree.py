"""규칙 트리와 AI 트리를 같은 영상으로 비교한다 (실행 중인 서버 API 사용).

    python scripts/measure_tree.py raw_clips/long_60min.MOV            # 올림 → 분석(캐시면 0원) → 규칙 트리 → AI 트리
    python scripts/measure_tree.py --project <id>                      # 이미 분석한 프로젝트로

AI 트리는 GET /projects/{id}/tree?ai=true (서버 GeminiClient, 유료). 두 번째 요청은 저장된 트리라 0원이어야 한다.
결과는 화면에 표로, local_results/measure/tree_<시각>.json 에 원자료로 남긴다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from measure_analysis import KRW_PER_USD, cost_usd  # noqa: E402


def analyze(api: httpx.Client, files: list[Path]) -> str:
    pid = api.post("/projects", json={"name": "트리 측정"}).raise_for_status().json()["project_id"]
    handles = [("files", (f.name, open(f, "rb"), "application/octet-stream")) for f in files]
    try:
        up = api.post(f"/projects/{pid}/clips", files=handles, timeout=None).raise_for_status().json()
    finally:
        for _, (_, fh, _) in handles:
            fh.close()
    api.patch(f"/projects/{pid}", json={"timeline": [c["clip_id"] for c in up["clips"]]}).raise_for_status()
    job = api.post(f"/projects/{pid}/analyze", json={"profile": {}}).raise_for_status().json()
    while job["status"] not in ("done", "failed", "canceled"):
        time.sleep(2)
        job = api.get(f"/jobs/{job['job_id']}").raise_for_status().json()
    usage = job["metrics"].get("ai_usage", {})
    print(f"분석 {job['status']} · Gemini {usage.get('requests')}회 (캐시 {usage.get('cache_hits')}) · "
          f"${cost_usd(usage.get('tokens_by_model', {}))[0]:.4f}")
    if job["status"] != "done":
        raise SystemExit(job.get("error"))
    return pid


def get_tree(api: httpx.Client, pid: str, ai: bool) -> tuple[dict, float]:
    t0 = time.time()
    doc = api.get(f"/projects/{pid}/tree", params={"ai": str(ai).lower()}, timeout=None).raise_for_status().json()
    return doc, time.time() - t0


def titles(doc: dict, level: int) -> list[str]:
    out = []

    def walk(nodes):
        for n in nodes:
            if n["level"] == level:
                out.append(f"{n['title']} ({(n['end'] - n['start']) / 60:.1f}분)")
            walk(n.get("children", []))
    walk(doc["tree"])
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="*", type=Path)
    ap.add_argument("--project", help="이미 분석한 프로젝트 id")
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    with httpx.Client(base_url=args.server + "/api", timeout=600) as api:
        pid = args.project or analyze(api, [p.resolve() for p in args.videos])
        rules, rules_sec = get_tree(api, pid, ai=False)
        ai, ai_sec = get_tree(api, pid, ai=True)
        again, again_sec = get_tree(api, pid, ai=True)

    usage = ai["meta"].get("ai_usage", {})
    usd, per_model = cost_usd(usage.get("tokens_by_model", {}))
    print(f"\n프로젝트 {pid}")
    print("| 항목 | 규칙 트리 | AI 트리 |\n| --- | --- | --- |")
    for k in ("l1", "l2", "l3", "l4"):
        print(f"| {k.upper()} 개수 | {rules['meta']['counts'][k]} | {ai['meta']['counts'][k]} |")
    print(f"| 만든 시간 | {rules_sec:.1f}초 | {ai_sec:.1f}초 |")
    print(f"| source | {rules['meta']['source']} | {ai['meta']['source']} |")
    print(f"| Gemini 요청 | 0 | {usage.get('requests', 0)}회 (캐시 {usage.get('cache_hits', 0)}) |")
    for model, (inp, out) in usage.get("tokens_by_model", {}).items():
        print(f"| 토큰 {model} | – | 입력 {inp:,} / 출력 {out:,} (${per_model.get(model) or 0:.4f}) |")
    print(f"| 비용 | $0 | ${usd:.4f} (약 {usd * KRW_PER_USD:,.0f}원) |")
    print(f"| 대사 보정 | – | {ai['meta'].get('corrections', 0)}건 |")
    print(f"\n두 번째 AI 요청: {again_sec:.2f}초, cached={again['cached']} (Gemini 다시 부르지 않음)")
    for name, doc in (("규칙", rules), ("AI", ai)):
        print(f"\n[{name}] L1: " + " / ".join(titles(doc, 1)))
        print(f"[{name}] L2: " + " / ".join(titles(doc, 2)))
    if ai["notes"] or ai["warnings"]:
        print("\nAI 안내·경고:", ai["notes"], ai["warnings"][:5])

    out_dir = Path("local_results/measure")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"tree_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"project_id": pid, "rules": rules, "ai": ai, "rules_sec": rules_sec, "ai_sec": ai_sec,
                               "again_sec": again_sec, "again_cached": again["cached"], "cost_usd": usd},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n원자료: {out}")


if __name__ == "__main__":
    main()
