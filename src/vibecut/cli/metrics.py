"""평가 지표 명령: 프로젝트 하나의 지표를 마크다운 표로 (발표·보고서용).

    vibecut metrics                 프로젝트 목록
    vibecut metrics <project_id>    그 프로젝트의 지표 표
"""

from __future__ import annotations

import argparse

from ..domain.models import Job
from ..eval.metrics import project_metrics, to_markdown
from ..services.editing import current_plan
from ..settings import get_settings
from ..storage.files import read_json
from ..storage.projects import ProjectStore


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("project_id", nargs="?", help="프로젝트 id (없으면 목록)")


def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = ProjectStore(settings.data_dir)
    if not args.project_id:
        for p in store.list():
            print(p.project_id, p.name, p.updated_at)
        return 0
    project, plan = current_plan(store, args.project_id)
    # 서버가 켜져 있어도 건드리지 않게 작업 기록은 읽기만 한다 (JobManager를 만들면 '중단됨' 처리가 일어남)
    jobs = []
    for path in (settings.data_dir / "jobs").glob("*.json"):
        job = Job.model_validate(read_json(path))
        if job.project_id == project.project_id:
            jobs.append(job)
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    print(to_markdown(project.name, project_metrics(project, store.load_analysis(project.project_id), plan, jobs)))
    return 0
