"""API 전체 흐름 (오프라인 모드, 실제 ffmpeg): 업로드 → 분석 → AI 가편집 → 수정 → 렌더 → 다운로드
→ 서버 종료 시 영상 삭제."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.media import make_clip
from vibecut.server.app import create_app
from vibecut.settings import load_settings

pytestmark = pytest.mark.slow


def wait_job(client: TestClient, job_id: str, timeout: float = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "canceled"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"작업이 끝나지 않음: {job}")


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    return [make_clip(d / "카페.mp4", 12, size="320x180", fps=30, bursts=True),
            make_clip(d / "거리.mov", 6, size="240x320", fps=25, bursts=True, tone=660)]


@pytest.fixture
def settings(tmp_path):
    return load_settings(api_key=None, ai_mode="offline", data_dir=tmp_path / "data", stt_engine="energy",
                         scene_engine="local")


def test_full_flow(settings, media):
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        config = client.get("/api/config").json()
        assert config["ai_mode"] == "offline" and config["ffmpeg"]["ok"]
        assert client.get("/api/config", headers={"host": "evil.example"}).status_code == 400   # DNS 리바인딩 차단

        pid = client.post("/api/projects", json={"name": "테스트 브이로그"}).json()["project_id"]
        files = [("files", (p.name, p.read_bytes(), "video/mp4")) for p in media]
        uploaded = client.post(f"/api/projects/{pid}/clips", files=files).json()
        ids = [c["clip_id"] for c in uploaded["clips"]]
        assert ids == ["c01", "c02"] and uploaded["clips"][1]["height"] == 320

        bad = client.post(f"/api/projects/{pid}/clips", files=[("files", ("x.txt", b"hello", "text/plain"))])
        assert bad.status_code == 400
        # Windows에서 %5C(\)가 경로로 풀려 proxy/..\clips\c01.mp4(원본)가 열리던 것: 없는 클립 id는 404
        assert client.get(f"/api/projects/{pid}/clips/..%5Cclips%5Cc01/proxy").status_code == 404

        assert client.post(f"/api/projects/{pid}/analyze", json={}).status_code == 422   # 타임라인이 비어 있음
        client.patch(f"/api/projects/{pid}", json={"timeline": ids})
        job = wait_job(client, client.post(f"/api/projects/{pid}/analyze", json={"profile": {}}).json()["job_id"])
        assert job["status"] == "done", job
        assert job["result"]["engines"]["stt"] == "energy" and job["result"]["scenes"] >= 2

        analysis = client.get(f"/api/projects/{pid}/analysis").json()
        assert len(analysis["lines"]) >= 4 and analysis["beats"]
        view = client.get(f"/api/projects/{pid}/plan").json()
        full = view["plan"]["duration"]
        assert 0 < full <= 18.0 and not [i for i in view["issues"] if i["level"] == "error"]

        sel = client.post(f"/api/projects/{pid}/select", json={"mode": "auto", "target_sec": 9.0}).json()
        assert sel["engine"] == "rule" and sel["plan"]["selection"]["mode"] == "auto"
        assert sel["plan"]["duration"] < full

        first = analysis["lines"][0]["seg_id"]
        before = client.post(f"/api/projects/{pid}/select", json={"mode": "all"}).json()["plan"]["duration"]
        after = client.patch(f"/api/projects/{pid}/plan/lines",
                             json={"changes": [{"seg_id": first, "keep": False}]}).json()["plan"]
        assert after["duration"] < before and after["lines"][first]["source"] == "user"

        style = after["styles"]["subtitle"] | {"size": 60, "background_box": True}
        put = client.put(f"/api/projects/{pid}/plan", json={"styles": {**after["styles"], "subtitle": style}}).json()
        assert put["plan"]["styles"]["subtitle"]["size"] == 60

        started = client.post(f"/api/projects/{pid}/render", json={"quality": "preview"}).json()
        again = client.post(f"/api/projects/{pid}/render", json={"quality": "preview"}).json()
        assert again["job_id"] == started["job_id"]                  # 도는 중이면 렌더를 또 걸지 않는다
        render_job = wait_job(client, started["job_id"])
        assert render_job["status"] == "done", render_job
        info = render_job["result"]["render"]
        assert abs(info["error_ms"]) <= 40
        project = client.get(f"/api/projects/{pid}").json()
        url = project["renders"][0]["url"]
        part = client.get(url, headers={"Range": "bytes=0-99"})
        assert part.status_code == 206 and len(part.content) == 100
        assert "attachment" in client.get(url).headers["content-disposition"]

        metrics = client.get(f"/api/projects/{pid}/metrics").json()
        assert metrics["output_sec"] == pytest.approx(after["duration"], abs=0.01)
        assert metrics["word_cuts"] == 0 and metrics["user_flips"] == 1

        deleted = client.delete(f"/api/projects/{pid}/clips/c02").json()
        assert deleted["timeline"] == ["c01"]
        assert (settings.data_dir / "cache" / "audio").is_dir()          # 분석이 뽑은 오디오가 있었다

    # 서버를 끄면 영상(원본·미리보기 사본·렌더)과 영상에서 뽑은 오디오를 남기지 않는다
    assert not any((settings.data_dir / "projects").iterdir())
    assert not (settings.data_dir / "cache" / "audio").exists()

    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:      # 다시 켜면 빈 상태
        assert client.get(f"/api/projects/{pid}").status_code == 404
        assert client.get("/api/projects").json() == []


def test_vertical_upload_makes_vertical_output_until_user_picks(settings, tmp_path):
    """세로로 찍은 영상을 올리면 화면이 계획을 다시 읽을 때 결과 비율이 9:16 (예전: 항상 16:9)."""
    vertical = make_clip(tmp_path / "세로.mp4", 3, size="180x320", audio=False)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        pid = client.post("/api/projects", json={"name": "세로"}).json()["project_id"]
        assert client.get(f"/api/projects/{pid}/plan").json()["plan"]["output"]["aspect"] == "16:9"   # 빈 프로젝트
        clip = client.post(f"/api/projects/{pid}/clips",
                           files=[("files", ("세로.mp4", vertical.read_bytes(), "video/mp4"))]).json()["clips"][0]
        client.patch(f"/api/projects/{pid}", json={"timeline": [clip["clip_id"]]})        # 화면이 하는 것과 같이
        output = client.get(f"/api/projects/{pid}/plan").json()["plan"]["output"]
        assert (output["aspect"], output["aspect_source"]) == ("9:16", "auto")
        chosen = {**output, "aspect": "16:9", "aspect_source": "user"}                       # 비율 버튼
        put = client.put(f"/api/projects/{pid}/plan", json={"output": chosen}).json()
        assert put["plan"]["output"]["aspect"] == "16:9"
        assert client.get(f"/api/projects/{pid}/plan").json()["plan"]["output"]["aspect"] == "16:9"
