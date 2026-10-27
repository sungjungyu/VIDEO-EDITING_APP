"""REST API (/api/...). 화면(web/js/api.js)은 이 엔드포인트만 쓴다.

프로젝트   POST/GET /projects, GET/PATCH/DELETE /projects/{pid}
클립       POST /projects/{pid}/clips (여러 개), DELETE …/clips/{cid}, GET …/clips/{cid}/file|proxy
분석       POST /projects/{pid}/analyze → 작업, GET …/analysis
편집 계획  GET/PUT /projects/{pid}/plan, PATCH …/plan/lines, POST …/select (AI 가편집), POST …/revise (채팅 수정)
렌더       POST /projects/{pid}/render → 작업, GET …/renders/{file}
작업       GET /jobs/{id}, POST /jobs/{id}/cancel, GET /projects/{pid}/jobs
기타       GET /config, GET /projects/{pid}/metrics
"""

from fastapi import APIRouter

from . import editing, projects, render

router = APIRouter(prefix="/api")
for module in (projects, editing, render):
    router.include_router(module.router)

