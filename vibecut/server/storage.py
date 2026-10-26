"""프로젝트 저장소 (디스크). 서버를 다시 켜도 업로드·분석·편집 계획·결과가 그대로 남는다.

data/
  projects/{project_id}/
      project.json      프로젝트 정보 (클립 목록, 타임라인 순서, 분석 상태, 렌더 목록)
      analysis.json     받아쓰기·장면·트리·컷 판단
      plan.json         편집 계획 (사용자 값 + 계산 결과)
      clips/            업로드 원본 (c01.mp4 …)
      proxy/            브라우저 미리보기용 540p 사본
      renders/          결과 영상
      work/             렌더 중간 파일 (끝나면 지움)
  jobs/{job_id}.json    작업 기록 (+ .log)
  cache/                같은 파일·설정이면 다시 쓰는 결과 (오디오, 받아쓰기, 장면, AI 응답)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from ..models import Analysis, EditPlan, Project, now_iso

_ID = re.compile(r"^[0-9a-f]{12}$")


class NotFound(LookupError):
    pass


def write_json(path: Path, data: dict | list) -> None:
    """임시 파일에 쓰고 바꿔치기 (쓰다가 꺼져도 파일이 깨지지 않게)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:          # Windows: 다른 스레드가 잠깐 읽고 있으면 실패할 수 있다
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


def read_json(path: Path):
    for attempt in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    return json.loads(path.read_text(encoding="utf-8"))


class ProjectStore:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.projects_dir = self.root / "projects"
        self.cache_dir = self.root / "cache"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()

    def lock(self, project_id: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(project_id, threading.RLock())

    def project_dir(self, project_id: str) -> Path:
        if not _ID.match(project_id or ""):
            raise NotFound("프로젝트를 찾을 수 없습니다.")
        return self.projects_dir / project_id

    # ------------------------------------------------------------ 프로젝트

    def create(self, name: str = "새 프로젝트") -> Project:
        project = Project(project_id=uuid.uuid4().hex[:12], name=name.strip()[:80] or "새 프로젝트")
        for sub in ("clips", "proxy", "renders"):
            (self.project_dir(project.project_id) / sub).mkdir(parents=True, exist_ok=True)
        self.save(project)
        return project

    def get(self, project_id: str) -> Project:
        path = self.project_dir(project_id) / "project.json"
        if not path.exists():
            raise NotFound("프로젝트를 찾을 수 없습니다.")
        return Project.model_validate(read_json(path))

    def save(self, project: Project) -> Project:
        project.updated_at = now_iso()
        with self.lock(project.project_id):
            write_json(self.project_dir(project.project_id) / "project.json", project.model_dump())
        return project

    def update(self, project_id: str, change: Callable[[Project], None]) -> Project:
        with self.lock(project_id):
            project = self.get(project_id)
            change(project)
            return self.save(project)

    def list(self) -> list[Project]:
        projects = []
        for path in self.projects_dir.glob("*/project.json"):
            try:
                projects.append(Project.model_validate(read_json(path)))
            except (OSError, ValueError):
                continue
        return sorted(projects, key=lambda p: p.updated_at, reverse=True)

    def delete(self, project_id: str) -> None:
        path = self.project_dir(project_id)
        if not path.exists():
            raise NotFound("프로젝트를 찾을 수 없습니다.")
        with self.lock(project_id):
            shutil.rmtree(path, ignore_errors=True)

    # ------------------------------------------------------------ 파일 경로

    def clip_path(self, project_id: str, stored_name: str) -> Path:
        return self.project_dir(project_id) / "clips" / Path(stored_name).name

    def proxy_path(self, project_id: str, clip_id: str) -> Path:
        return self.project_dir(project_id) / "proxy" / f"{clip_id}.mp4"

    def render_path(self, project_id: str, file_name: str) -> Path:
        return self.project_dir(project_id) / "renders" / Path(file_name).name

    def work_dir(self, project_id: str, name: str) -> Path:
        return self.project_dir(project_id) / "work" / name

    def clip_files(self, project: Project) -> dict[str, Path]:
        return {c.clip_id: self.clip_path(project.project_id, c.stored_name) for c in project.clips}

    @staticmethod
    def next_clip_id(project: Project) -> str:
        used = {int(c.clip_id[1:]) for c in project.clips if c.clip_id[1:].isdigit()}
        n = 1
        while n in used:
            n += 1
        return f"c{n:02d}"

    # ------------------------------------------------------------ 분석·계획

    def load_analysis(self, project_id: str) -> Analysis | None:
        path = self.project_dir(project_id) / "analysis.json"
        return Analysis.model_validate(read_json(path)) if path.exists() else None

    def save_analysis(self, project_id: str, analysis: Analysis) -> None:
        write_json(self.project_dir(project_id) / "analysis.json", analysis.model_dump())

    def load_plan(self, project_id: str) -> EditPlan:
        path = self.project_dir(project_id) / "plan.json"
        return EditPlan.model_validate(read_json(path)) if path.exists() else EditPlan()

    def save_plan(self, project_id: str, plan: EditPlan) -> None:
        with self.lock(project_id):
            write_json(self.project_dir(project_id) / "plan.json", plan.model_dump())

    # ------------------------------------------------------------ 정리

    def cleanup(self, retention_days: int) -> int:
        """오래된 렌더 중간 폴더와 오래된 미리보기 렌더를 지운다 (원본·계획은 지우지 않는다)."""
        limit = time.time() - retention_days * 86400
        removed = 0
        for work in self.projects_dir.glob("*/work/*"):
            if work.stat().st_mtime < limit or not any(work.iterdir()):
                shutil.rmtree(work, ignore_errors=True)
                removed += 1
        for preview in self.projects_dir.glob("*/renders/*_preview.mp4"):
            if preview.stat().st_mtime < limit:
                preview.unlink(missing_ok=True)
                removed += 1
        return removed
