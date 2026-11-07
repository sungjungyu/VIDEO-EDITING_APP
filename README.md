# VIBE CUT

여러 클립을 올리면 **받아쓰기 · 장면 분석 · AI 판단**으로 편집 계획(EditPlan)을 만들고, FFmpeg로 한 번에 렌더하는 브이로그 편집 도구입니다.

- 문장 단위 컷 판단 (자체 규칙 + Gemini), 목표 분량에 맞춘 AI 가편집, 채팅으로 수정 요청
- 장소 → 일 → 상황 → 대사 4단 장면 트리로 직접 고르기
- 미리보기와 같은 자막 스타일로 렌더 (ASS, 카라오케), 16:9 / 9:16
- Gemini 키가 없거나 한도를 넘겨도 동작 (로컬 Whisper · 화면 변화 감지 · 규칙 판단으로 대체)

## 빠른 시작

Python 3.12 이상이 필요합니다. ffmpeg는 `imageio-ffmpeg`에 들어 있어 따로 설치하지 않아도 됩니다.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"            # 앱 + 개발 도구 (로컬 Whisper까지: ".[dev,whisper]")

copy .env.example .env             # .env에 GEMINI_API_KEY 입력 (없으면 오프라인 모드)

vibecut serve                      # 웹 화면 → http://127.0.0.1:8000
```

명령줄 (`vibecut <명령> --help`로 옵션 확인):

```powershell
vibecut edit input.mp4                                   # 분석 → 편집 → 렌더: input.mp4 → output.mp4
vibecut edit a.mp4 b.mp4 -o vlog.mp4 --target 90 --prompt "카페 장면 위주로"   # AI 가편집으로 90초
vibecut edit input.mp4 --offline                         # Gemini 없이
vibecut transcribe --input .\raw_clips --engine gemini   # 받아쓰기만 → transcript.json + .md
vibecut scenes --input .\raw_clips                       # 장면 분석만 → scenes.json + .md
vibecut metrics <프로젝트 id>                             # 평가 지표 표
```

## 프로젝트 구조

```
├─ src/vibecut/           백엔드 (계층 구조: 위는 아래를 쓰고 아래는 위를 모른다)
│  ├─ server/             HTTP 입구: FastAPI 조립·라우트 (서비스만 부른다)
│  ├─ cli/                명령줄 입구: serve · edit · transcribe · scenes · metrics
│  ├─ services/           사용 사례 (웹·명령줄 공통): 프로젝트·편집·분석 작업·렌더 작업, 작업 큐
│  ├─ analysis/           원본 이해: 받아쓰기(stt/) · 장면 분석(scenes/) · 음량·무음 · 4단 트리 · 컷 판단
│  ├─ editing/            편집 계획 계산 · 자막 장면 · AI 가편집 · 수정 요청
│  ├─ render/             EditPlan → FFmpeg 필터 그래프 · ASS 자막 · 글꼴
│  ├─ eval/               평가 지표
│  ├─ ai/                 Gemini 호출 전부 (글 판단·영상 분석·받아쓰기, 재시도·캐시·사용량)
│  ├─ media/              ffmpeg 실행 · 영상 정보 · 변환
│  ├─ storage/            프로젝트 저장소 · 결과 캐시 · 원자적 JSON
│  ├─ domain/             데이터 모델(EditPlan 등) · 구간·시간·자막 글자·한국어 규칙 (순수 코드)
│  └─ settings.py · errors.py · log.py
├─ web/                   화면: index.html · css/(base·layout·panels/) · js/(core·subtitle·panels)
├─ tests/                 unit/(패키지별) · integration/(실제 ffmpeg·API) · regression/(골든) · js/
├─ scripts/               개발 도구 (Gemini 연결 확인, 받아쓰기 엔진 비교표)
├─ docs/                  구조 설명, 설계 결정(adr/), 지난 기획서(archive/)
├─ .github/workflows/     CI (린트 + 테스트)
├─ .env.example           설정 예시 → .env로 복사
└─ pyproject.toml         의존성·명령·pytest·ruff 설정
```

실행 중 생기는 `data/`(프로젝트·작업·캐시)와 `.env`, `.venv/`는 git에 올라가지 않습니다.

## 개발

```powershell
pytest -q                       # 전체 테스트 (렌더 정확도 실측·골든 회귀·계층 규칙 포함, Gemini 호출 없음)
pytest -q -m "not slow"         # 빠른 테스트만 (실제 영상 렌더 제외)
ruff check .                    # 린트
node tests/js/wrap.test.mjs     # 화면 자막 줄바꿈 = 서버 줄바꿈
python scripts/check_gemini.py  # API 키·모델 이름 확인 (사용량 0)
vibecut serve --reload          # 코드를 고치면 자동으로 다시 시작
```

`tests/regression/`은 리팩터링 전 코드로 만든 결과(프롬프트·AI 캐시 키·편집 계획·API 모양)와 지금 결과를 비교합니다. 기능을 일부러 바꿨을 때만 `VIBECUT_UPDATE_GOLDEN=1 pytest tests/regression`으로 기준을 다시 만듭니다.

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
- 설계 결정: [0001 렌더 엔진 단일화](docs/adr/0001-렌더-엔진-단일화.md) · [0002 저장소 구조 정리](docs/adr/0002-저장소-구조-정리.md) · [0003 계층 구조와 최적화](docs/adr/0003-계층-구조와-최적화.md)
- [받아쓰기 엔진 비교](docs/stt_비교.md)
- [지난 기획서·가이드 (archive)](docs/archive/): v1·v2 시절 문서, 내용은 작성 당시 그대로
