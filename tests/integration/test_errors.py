"""API 오류 응답: 요청이 잘못되면 422, 서버 쪽 문제(저장 파일 깨짐 등)는 500 (예전에는 ValueError면 모두 422)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from vibecut.server.app import create_app


def test_bad_request_is_422_and_broken_file_is_500(make_settings, tmp_path):
    settings = make_settings(tmp_path, ai_mode="offline")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        pid = client.post("/api/projects", json={"name": "오류"}).json()["project_id"]

        bad = client.patch(f"/api/projects/{pid}", json={"timeline": ["c99"]})       # 없는 클립
        assert bad.status_code == 422 and "타임라인" in bad.json()["detail"]

        (tmp_path / "projects" / pid / "plan.json").write_text("{깨진 JSON", encoding="utf-8")
        broken = client.get(f"/api/projects/{pid}/plan")
        assert broken.status_code == 500 and "깨진" not in broken.json()["detail"]  # 내부 메시지는 숨긴다

        # JSON은 맞지만 모양이 틀린 저장 파일 (pydantic 검증 오류도 ValueError) — 예전에는 422로 사용자 탓이 됐다
        (tmp_path / "projects" / pid / "plan.json").write_text('{"output": {"aspect": "4:3"}}', encoding="utf-8")
        assert client.get(f"/api/projects/{pid}/plan").status_code == 500
