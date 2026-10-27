# VIBE CUT

여러 클립을 올리면 **받아쓰기 · 장면 분석 · AI 판단**으로 편집 계획(EditPlan)을 만들고, FFmpeg로 한 번에 렌더하는 브이로그 편집 도구입니다.

- 문장 단위 컷 판단 (자체 규칙 + Gemini), 목표 분량에 맞춘 AI 가편집, 채팅으로 수정 요청
- 장소 → 일 → 상황 → 대사 4단 장면 트리로 직접 고르기
- 미리보기와 같은 자막 스타일로 렌더 (ASS, 카라오케), 16:9 / 9:16
- Gemini 키가 없거나 한도를 넘겨도 동작 (로컬 Whisper · 화면 변화 감지 · 규칙 판단으로 대체)

## 빠른 시작

Python 3.10 이상이 필요합니다. ffmpeg는 `imageio-ffmpeg`에 들어 있어 따로 설치하지 않아도 됩니다.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"            # 앱 + 개발 도구 (로컬 Whisper까지: ".[dev,whisper]")

copy .env.example .env             # .env에 GEMINI_API_KEY 입력 (없으면 오프라인 모드)

vibecut-server                     # 웹 화면 → http://127.0.0.1:8000
```

명령줄로 한 번에 편집:

```powershell
vibecut input.mp4                                            # input.mp4 → output.mp4
vibecut a.mp4 b.mp4 -o vlog.mp4 --target 90 --prompt "카페 장면 위주로"
vibecut input.mp4 --offline                                  # Gemini 없이
```

## 프로젝트 구조

```
├─ src/vibecut/           백엔드 패키지
│  ├─ cli.py              명령줄 편집 (vibecut)
│  ├─ settings.py         환경 변수·.env → 설정 (모델 이름·API 키는 여기 한 곳)
│  ├─ models.py           데이터 계약 (EditPlan, Line, Scene, TreeNode, StyleSpec, Job …)
│  ├─ server/             FastAPI 앱(vibecut-server), REST API, 작업 큐, 저장소, 파이프라인
│  ├─ ai/                 Gemini 클라이언트, 컷 판단, AI 가편집, 수정 요청
│  │  └─ engines/         받아쓰기·장면 분석 원본 엔진 (단독 CLI 포함)
│  ├─ edit/               편집 계획 계산 (남길 구간, 단어 경계, 쉼 압축, 프레임 정렬)
│  ├─ render/             EditPlan → FFmpeg 필터 그래프, ASS 자막, 글꼴
│  ├─ media/              ffmpeg 찾기·실행·정보 읽기·오디오 추출·프록시
│  └─ eval/               평가 지표
├─ web/                   브라우저 화면 (index.html · css · js ES 모듈)
├─ tests/                 pytest 테스트, js/ 화면 테스트, fixtures/ 테스트용 영상 생성·공용 데이터
├─ scripts/               개발 도구 (Gemini 연결 확인, 받아쓰기 엔진 비교표)
├─ docs/                  구조 설명, 설계 결정(adr/), 지난 기획서(archive/)
├─ .github/workflows/     CI (린트 + 테스트)
├─ .env.example           설정 예시 → .env로 복사
└─ pyproject.toml         의존성·명령·pytest·ruff 설정
```

실행 중 생기는 `data/`(프로젝트·작업·캐시)와 `.env`, `.venv/`는 git에 올라가지 않습니다.

## 개발

```powershell
pytest -q                       # 전체 테스트 (렌더 정확도 실측 포함, Gemini 호출 없음)
ruff check .                    # 린트
node tests/js/wrap.test.mjs     # 화면 자막 줄바꿈 = 서버 줄바꿈
python scripts/check_gemini.py  # API 키·모델 이름 확인 (사용량 0)
python -m vibecut.eval.metrics <프로젝트 id>                   # 평가 지표 표
uvicorn vibecut.server.app:create_app --factory --reload       # 코드 수정 시 자동 재시작
```

엔진 단독 실행:

```powershell
python -m vibecut.ai.engines.transcriber --input .\raw_clips --engine gemini --out transcript.json
python -m vibecut.ai.engines.scene_analyzer --input .\raw_clips --out scenes.json
```

GitHub Actions가 push·PR마다 린트와 테스트를 돌립니다.

## 설정

환경 변수 또는 `.env`로 바꿉니다 (실제 환경 변수가 우선). 전체 목록은 `src/vibecut/settings.py`에 있습니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | 없으면 오프라인 모드 |
| `VIBECUT_AI_MODE` | 키가 있으면 `live` | `offline`이면 네트워크를 쓰지 않음 (저장된 AI 응답 재생 또는 규칙 판단) |
| `STT_ENGINE` | `auto` | `gemini` → `whisper-local` → `energy` 순서로 대체 |
| `SCENE_ENGINE` | `auto` | `gemini` 또는 `local`(화면 변화 감지) |
| `VIBECUT_DATA_DIR` | `./data` | 프로젝트·작업·캐시 폴더 |
| `VIBECUT_HOST` / `VIBECUT_PORT` | `127.0.0.1` / `8000` | 서버 주소 (인증이 없으니 외부 공개 주의) |

## 문서

- [v3 구조와 실행](docs/VIBECUT_v3_구조와_실행.md): 파이프라인, EditPlan, 알고리즘, API, 팀원별 담당
- [ADR 0001 렌더 엔진 단일화](docs/adr/0001-렌더-엔진-단일화.md) · [ADR 0002 저장소 구조 정리](docs/adr/0002-저장소-구조-정리.md)
- [받아쓰기 엔진 비교](docs/stt_비교.md)
- [지난 기획서·가이드 (archive)](docs/archive/): v1·v2 시절 문서, 내용은 작성 당시 그대로
