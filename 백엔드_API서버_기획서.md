# 백엔드 (팀원2) API 서버 기획서

> 이 문서는 AI 영상 가편집 프로젝트의 **팀원2 (백엔드 개발자)** 담당 영역에 대한 기획서입니다.
> 팀원4(미디어 엔진) 기획 과정에서 이미 확정된 연동 사양을 그대로 반영했고, 여기에 백엔드 고유의 결정 사항(저장 방식, 인증, 웹소켓 연결 방식, 엔드포인트 스펙)을 추가로 정리했습니다.
> 다른 팀원(팀원1 프론트엔드, 팀원3 AI 파이프라인, 팀원4 미디어 엔진) 담당 클로드가 연동점을 확인할 때도 참고할 수 있도록 작성했습니다.

---

## 1. 담당 범위 요약

FastAPI/Uvicorn 기반 비동기 웹 서버를 구축하고, 파일 업로드부터 AI 분석 호출, 렌더링 요청 처리, 실시간 진행률 전송까지 전체 시스템 흐름을 총괄합니다.

---

## 2. 확정된 아키텍처 결정 사항과 근거

### 2-1. 파일 저장: 로컬 디스크

- 업로드 영상과 렌더링 결과물 모두 서버 로컬 디스크(`uploads/`, `outputs/`)에 저장합니다.
- **근거**: 캡스톤 시연 규모에서는 S3 등 클라우드 스토리지가 과설계입니다. 계정 생성, 버킷 설정, 인증 키 관리에 드는 시간이 실제 개발 시간을 잠식합니다. R&R 원문에도 이미 "uploads 폴더 저장"으로 명시되어 있습니다. 추후 상업화 단계에서 저장 로직을 함수 단위로 잘 감싸두면 S3 전환이 어렵지 않습니다.

### 2-2. 데이터베이스: 미사용 (MVP)

- 이번 개발 범위(여름방학 개발 → 캡스톤 MVP 발표)에서는 **스타일 프리셋(매운맛/순한맛/정석맛) 방식만 사용**하고, 사용자별 편집 이력을 학습하는 개인화 기능은 포함하지 않기로 확정했습니다.
- 개인화 학습 기능이 없으므로 영구 저장이 필요한 사용자 데이터가 없어, DB 없이 파일 시스템 + 인메모리 상태 관리만으로 충분합니다.
- **확장 계획**: 개인 편집 스타일 학습 기능은 학기 중 캡스톤 디자인 수강과 이어지는 후속 단계에서, 사용자 인증 및 편집 이력 저장을 위한 DB(예: SQLite → PostgreSQL)를 도입하며 함께 구현합니다.

### 2-3. 사용자 인증: 없음 (MVP)

- 로그인/회원가입 없이 누구나 바로 업로드해서 사용할 수 있는 데모 형태로 갑니다.
- 인증이 없으므로 **`job_id`가 사실상 유일한 요청 식별자** 역할을 합니다. `/upload` 시점에 발급되는 `job_id`를 프론트엔드가 이후 모든 요청(분석/렌더링/진행률 조회)에 계속 사용합니다.

### 2-4. 작업 상태 관리: 인메모리 딕셔너리

- DB가 없으므로 `job_id`별 진행 상태는 서버 프로세스 메모리 내 Python 딕셔너리로 관리합니다.
- 서버 재시작 시 상태가 초기화되는 한계가 있지만, 소규모 데모 단계에서는 문제가 되지 않습니다.

```python
jobs = {
    "abc123...": {
        "status": "uploaded" | "analyzed" | "rendering" | "done" | "error",
        "source_path": "uploads/abc123.mp4",
        "result_path": "outputs/abc123_final.mp4" | None,
        "created_at": "..."
    }
}
```

### 2-5. `/upload`와 `/edit` 분리 (2단계)

- 파일 업로드(가벼운 작업)와 AI 분석(Whisper+Gemini, 시간이 걸리는 작업)을 하나로 묶지 않고 별도 엔드포인트로 분리했습니다.
- **근거**:
  1. 두 작업을 하나로 묶으면 사용자가 업로드 버튼을 누른 순간부터 분석 완료까지 하나의 로딩 화면만 봐야 해서 단계별 피드백을 줄 수 없습니다.
  2. 분리하면 "업로드 완료" → "AI 분석 중" 등 단계별 상태를 프론트엔드가 구분해서 보여줄 수 있습니다.
  3. 추후 "다른 스타일 프리셋으로 재분석하고 싶다" 같은 요구가 생겼을 때, `/edit`만 재호출하면 되므로 업로드부터 반복할 필요가 없습니다.

### 2-6. 비동기 렌더링 처리: `run_in_threadpool` (Celery 미사용)

> 이 결정은 팀원4(미디어 엔진) 기획 과정에서 먼저 확정되었으며, 백엔드가 구현을 담당합니다.

- 렌더링은 수십 초~몇 분이 걸리는 무거운 작업이라, FastAPI의 비동기 이벤트 루프를 막지 않도록 별도 처리가 필요합니다.
- **Celery + Redis(정식 작업 큐)는 채택하지 않았습니다.** 프로덕션급 안정성을 갖지만, 캡스톤 시연 규모에서는 인프라 부담(Redis 설치, 워커 프로세스 관리)이 개발 리소스 대비 과합니다.
- 대신 **FastAPI `BackgroundTasks` + `run_in_threadpool`**로 스레드풀에서 렌더링을 실행해, 추가 인프라 없이 이벤트 루프 블로킹을 방지합니다.
- 팀원4가 작성하는 `render_video()`는 **순수 블로킹(동기) 함수**로 제공되며, 백엔드가 이를 스레드풀로 감싸는 역할을 담당합니다.

### 2-7. 웹소켓 연결 방식과 시점

- 경로: `ws://서버주소/ws/{job_id}` — `job_id`별 전용 웹소켓 커넥션.
- **연결 시점**: 프론트엔드는 `/render` 호출 **직전**에 웹소켓을 먼저 연결합니다.
- **근거**: `/render`를 먼저 호출한 뒤 웹소켓을 연결하면, 렌더링이 빠르게 끝나는 짧은 영상의 경우 초반 진행률 메시지(예: "cutting 5%")를 놓칠 수 있습니다. 웹소켓을 먼저 열어두어야 첫 메시지부터 안전하게 수신할 수 있습니다.
- 인증이 없으므로 `job_id`가 이 웹소켓 커넥션을 식별하는 유일한 키입니다.

---

## 3. 전체 요청 흐름

```
1. POST /upload         → job_id 발급, 원본 영상 uploads/ 저장
2. POST /edit             → job_id로 Whisper+Gemini 분석 실행 (팀원3 파이프라인 호출)
3. WebSocket 연결          → ws://.../ws/{job_id}  (렌더링 시작 전 미리 연결)
4. POST /render            → job_id + edit_data(cuts, subtitles, style_preset) 전송
                              → run_in_threadpool로 팀원4 render_video() 백그라운드 실행
5. 웹소켓으로 진행률 실시간 수신 → 완료 시 최종 파일 경로(result_url) 수신
```

---

## 4. 엔드포인트 상세 스펙

### 4-1. `POST /upload`

**요청**: `multipart/form-data`로 영상 파일 전송

**응답**:
```json
{
  "job_id": "abc123...",
  "filename": "original_video.mp4",
  "status": "uploaded"
}
```

### 4-2. `POST /edit`

**요청**:
```json
{ "job_id": "abc123..." }
```

**응답** (팀원3 AI 파이프라인 결과를 그대로 전달):
```json
{
  "job_id": "abc123...",
  "segments": [
    {
      "start": 0.0,
      "end": 3.5,
      "text": "안녕하세요 오늘은",
      "words": [{"word": "안녕하세요", "start": 0.0, "end": 0.8}],
      "suggested_cut": false
    }
  ],
  "status": "analyzed"
}
```

### 4-3. WebSocket `/ws/{job_id}`

서버 → 프론트엔드 진행률 메시지:
```json
{ "stage": "cutting", "percent": 5 }
{ "stage": "generating_subtitles", "percent": 15 }
{ "stage": "encoding", "percent": 20 }
{ "stage": "done", "percent": 100, "result_url": "/download/abc123.mp4" }
```

에러 발생 시:
```json
{ "stage": "error", "error_type": "FFmpegCuttingError", "message": "..." }
```

> stage 값(`cutting`, `generating_subtitles`, `encoding`, `done`)과 percent 구간(0~20% 컷 편집, 20~95% 인코딩, 100% 완료)은 팀원4 기획서와 동일하게 맞춥니다.

### 4-4. `POST /render`

**요청** (팀원4가 정의한 `edit_data` 스키마와 동일):
```json
{
  "job_id": "abc123...",
  "cuts": [{"start": 0.0, "end": 3.5}, {"start": 5.0, "end": 12.0}],
  "subtitles": [
    {
      "start": 0.0, "end": 3.5, "text": "안녕하세요 오늘은",
      "words": [{"word": "안녕하세요", "start": 0.0, "end": 0.8}]
    }
  ],
  "style_preset": "매운맛"
}
```

**즉시 응답** (접수 확인만, 실제 진행 상황은 웹소켓으로 전달):
```json
{ "job_id": "abc123...", "status": "rendering_started" }
```

---

## 5. 폴더 구조 (제안)

```
backend/
├── main.py                    # FastAPI 앱, 라우터 등록
├── routers/
│   ├── upload.py                # /upload
│   ├── edit.py                   # /edit (팀원3 파이프라인 호출)
│   └── render.py                  # /render + WebSocket
├── job_store.py                  # 인메모리 job 상태 관리
├── websocket_manager.py          # job_id별 웹소켓 커넥션 관리
├── uploads/                       # 원본 영상 저장
├── outputs/                        # 최종 렌더링 결과 저장
└── exceptions.py                   # 에러 응답 매핑
```

---

## 6. 예외 처리 (팀원4 기획서와 연동)

팀원4(`exceptions.py`)에서 발생하는 커스텀 예외를 백엔드가 catch하여 웹소켓 에러 메시지로 변환합니다.

| 팀원4 예외 클래스 | 발생 상황 | 백엔드 처리 |
|---|---|---|
| `InvalidCutRangeError` | cuts 구간이 겹치거나 역전되거나 영상 길이를 벗어남 | 웹소켓으로 `error_type: "InvalidCutRangeError"` 전송, job 상태를 `error`로 변경 |
| `FFmpegCuttingError` | 컷 편집 단계 실패 (fallback 재인코딩도 실패) | 동일 |
| `SubtitleGenerationError` | .ass 파일 생성 실패 (폰트 없음, 스타일 프리셋 오류 등) | 동일 |
| `FFmpegEncodingError` | 최종 인코딩 단계 실패 | 동일 |

---

## 7. 팀원1(프론트엔드)과 협의가 필요한 사항

- `/edit` 응답의 `segments` 구조가 실제 타임라인 UI 렌더링에 필요한 필드와 일치하는지 확인 필요.
- `cuts` vs `deletions` 스키마 관련, 팀원4 기획서 §7에서 다룬 협의 사항과 동일하게 적용됨(프론트엔드는 최종적으로 `cuts` 형태로 `/render`에 전송).

## 8. 팀원3(AI 파이프라인)과 협의가 필요한 사항

- `/edit`이 팀원3의 분석 함수를 어떤 방식으로 호출할지(직접 함수 호출 vs 별도 프로세스) 확정 필요.
- `segments`의 `words`(단어 단위 타임스탬프) 필드가 팀원4의 카라오케 자막 하이라이트에 필요하므로, 반드시 포함되도록 팀원3과 스키마 합의 필요.

---

## 9. 확장 목표 (MVP 이후)

1. 사용자 인증 도입 (개인화 학습 기반 마련)
2. DB 도입 (SQLite → PostgreSQL), 사용자별 편집 이력 저장
3. 인메모리 job 상태를 DB 기반으로 전환 (서버 재시작에도 상태 유지)
4. Celery + Redis 전환 검토 (동시 사용자 규모가 커질 경우)
