"""분석 1회(또는 캐시 재실행 포함 여러 회)의 시간·Gemini 호출·토큰·비용을 잰다.

실행 중인 서버(vibecut serve)의 API를 그대로 쓴다: 새 프로젝트 → 업로드 → 타임라인 → 분석 → 작업 폴링.
같은 영상을 다시 돌리면 받아쓰기·장면 분석 캐시(data/cache)를 쓰므로 두 번째 실행이 "캐시 재실행" 값이 된다.

    python scripts/measure_analysis.py raw_clips/long_60min.MOV --runs 2

결과는 화면에 표로, local_results/measure/<시각>.json 에 원자료로 남긴다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# 공식 가격표 https://ai.google.dev/gemini-api/docs/pricing (2026-11-10 확인, 유료 등급, USD / 1M 토큰)
# gemini-3.5-flash 는 2026-12-31까지 값. 2027-01-01부터 입력 1.50 / 출력 7.50
PRICES = {
    "gemini-3.5-flash":       (0.75, 3.75),
    "gemini-3.5-flash-lite":  (0.30, 2.50),
    "gemini-3.5-transcribe":  (2.00, 12.00),
}
KRW_PER_USD = 1400   # 표시용 환율 (대략)

STAGE_NAMES = {
    "audio": "오디오 추출",
    "transcribe_and_scenes": "받아쓰기·영상 분석",
    "judge": "컷 판단",
    "beats": "장면 나누기",
}


def media_duration(path: Path) -> float:
    try:
        import imageio_ffmpeg
        out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stderr
        h, m, s = out.split("Duration: ")[1].split(",")[0].split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return 0.0


def cost_usd(tokens_by_model: dict) -> tuple[float, dict]:
    total, rows = 0.0, {}
    for model, (inp, out) in tokens_by_model.items():
        price = PRICES.get(model)
        if price is None:
            rows[model] = None
            continue
        usd = inp / 1e6 * price[0] + out / 1e6 * price[1]
        rows[model] = round(usd, 5)
        total += usd
    return round(total, 5), rows


def run_once(api: httpx.Client, files: list[Path]) -> dict:
    project = api.post("/projects", json={"name": "측정"}).raise_for_status().json()
    pid = project["project_id"]

    t0 = time.time()
    handles = [("files", (f.name, open(f, "rb"), "application/octet-stream")) for f in files]
    try:
        up = api.post(f"/projects/{pid}/clips", files=handles, timeout=None).raise_for_status().json()
    finally:
        for _, (_, fh, _) in handles:
            fh.close()
    upload_sec = time.time() - t0
    api.patch(f"/projects/{pid}", json={"timeline": [c["clip_id"] for c in up["clips"]]}).raise_for_status()

    t1 = time.time()
    job = api.post(f"/projects/{pid}/analyze", json={"profile": {}}).raise_for_status().json()
    last = None
    while job["status"] not in ("done", "failed", "canceled"):
        time.sleep(2)
        job = api.get(f"/jobs/{job['job_id']}").raise_for_status().json()
        line = f"  {job['progress']:5.1f}%  {job['stage']}  {job['message']}"
        if line != last:
            print(line, flush=True)
            last = line
    wall_sec = time.time() - t1
    if job["status"] != "done":
        raise SystemExit(f"분석 {job['status']}: {job.get('error')}")

    usage = job["metrics"].get("ai_usage", {})
    total, per_model = cost_usd(usage.get("tokens_by_model", {}))
    return {
        "project_id": pid,
        "job_id": job["job_id"],
        "upload_sec": round(upload_sec, 1),
        "analysis_wall_sec": round(wall_sec, 1),
        "analysis_elapsed_sec": job["metrics"].get("elapsed_sec"),
        "stages_sec": job["metrics"].get("stages", {}),
        "ai_usage": usage,
        "cost_usd": total,
        "cost_usd_by_model": per_model,
        "result": job["result"],
    }


def report(runs: list[dict], source_sec: float) -> None:
    for i, r in enumerate(runs, 1):
        u = r["ai_usage"]
        print(f"\n## 실행 {i}{' (캐시 재실행)' if i > 1 else ''}")
        print(f"업로드 {r['upload_sec']}초 · 분석 {r['analysis_elapsed_sec']}초 (원본 {source_sec / 60:.1f}분)")
        for key, sec in r["stages_sec"].items():
            print(f"  - {STAGE_NAMES.get(key, key)}: {sec}초")
        print(f"Gemini 요청 {u.get('requests', 0)}회 · 캐시 적중 {u.get('cache_hits', 0)}회")
        for model, n in u.get("by_model", {}).items():
            inp, out = u.get("tokens_by_model", {}).get(model, [0, 0])
            usd = r["cost_usd_by_model"].get(model)
            usd_text = f"${usd:.4f}" if usd is not None else "단가 없음"
            print(f"  - {model}: {n}회, 입력 {inp:,} / 출력 {out:,} 토큰, {usd_text}")
        print(f"비용 합계 ${r['cost_usd']:.4f} (약 {r['cost_usd'] * KRW_PER_USD:,.0f}원)")
        res = r["result"]
        print(f"결과: 문장 {res.get('lines')} · 장면 {res.get('scenes')} · 비트 {res.get('beats')} · "
              f"자름 제안 {res.get('cut_suggested')} · 엔진 {res.get('engines')}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--runs", type=int, default=1, help="같은 영상으로 몇 번 돌릴지 (2 이상이면 캐시 재실행 포함)")
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    files = [p.resolve() for p in args.videos]
    for f in files:
        if not f.exists():
            raise SystemExit(f"파일 없음: {f}")
    source_sec = sum(media_duration(f) for f in files)

    with httpx.Client(base_url=args.server + "/api", timeout=60) as api:
        config = api.get("/config").raise_for_status().json()
        print(f"서버 {config['version']} · AI 모드 {config['ai_mode']} · 판단 {config['judge_mode']} · 모델 {config['models']}")
        runs = []
        for i in range(args.runs):
            print(f"\n=== 실행 {i + 1}/{args.runs}: {', '.join(f.name for f in files)} ===")
            runs.append(run_once(api, files))

    report(runs, source_sec)
    out_dir = Path("local_results/measure")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"files": [str(f) for f in files], "source_sec": source_sec, "config": config,
                               "prices_usd_per_1m": PRICES, "runs": runs}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n원자료: {out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
