"""REST API (/api/...). 화면(web/js/core/api.js)은 이 엔드포인트만 쓴다.
핸들러는 요청 확인 → 서비스 호출 → 응답 가공만 한다 (업무 규칙은 services에).

설정       GET /config                                                           system.py
프로젝트   POST/GET /projects, GET/PATCH/DELETE /projects/{pid}                  projects.py
클립       POST /projects/{pid}/clips (여러 개), DELETE …/clips/{cid}, GET …/clips/{cid}/file|proxy
분석       POST /projects/{pid}/analyze → 작업, GET …/analysis                   editing.py
편집 계획  GET/PUT /projects/{pid}/plan, PATCH …/plan/lines, POST …/select (AI 가편집), POST …/revise (채팅 수정)
렌더       POST /projects/{pid}/render → 작업, GET …/renders/{file}              render.py
작업       GET /jobs/{id}, POST /jobs/{id}/cancel, GET /projects/{pid}/jobs
평가 지표  GET /projects/{pid}/metrics
배경음악   GET/POST /projects/{pid}/music (곡·추천 / 내 음악 올리기), GET …/music/file, GET /music/{id}/file   music.py
평가 정답  GET/POST /projects/{pid}/bench-case (검수한 살림/뺌 → data/bench, vibecut bench로 채점)   editing.py
"""

from fastapi import APIRouter

from . import editing, music, projects, render, system

router = APIRouter(prefix="/api")
for module in (system, projects, editing, music, render):
    router.include_router(module.router)
