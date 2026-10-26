# VIBE CUT v3 — 구조와 실행

작성: 성준규 · 2026-10-27 · 브랜치 `feature/single-pipeline`

세 갈래였던 코드(main.py MoviePy 렌더 / media_engine FFmpeg 렌더 / 쓰이지 않던 backend 앱)를 **파이프라인 하나 + 데이터 계약 하나(EditPlan)**로 합쳤다. 이 문서는 무엇이 어디로 갔는지, 어떻게 실행하는지, 각자 어디를 고치면 되는지를 정리한다.

---

## 1. 실행

```powershell
pip install -r requirements.txt          # 필수 (ffmpeg는 imageio-ffmpeg에 들어 있어 따로 설치하지 않아도 된다)
pip install -r requirements-whisper.txt  # 선택: 로컬 Whisper 받아쓰기 (Gemini를 못 쓸 때 대체 엔진)
pip install -r requirements-dev.txt      # 개발: pytest, ruff

python app.py                            # 웹 화면 → http://127.0.0.1:8000
python main.py a.mp4 b.mp4 -o out.mp4 --target 90 --prompt "카페 장면 위주로"   # 명령줄로 한 번에
python main.py input.mp4 --offline       # Gemini 없이 (규칙 판단 + 로컬 엔진)
python -m vibecut.eval.metrics <프로젝트 id>   # 평가 지표 표 (발표·보고서용)
python scripts/check_gemini.py           # 키·모델 이름 확인 (사용량 0)
pytest -q                                # 테스트 94개 (렌더 정확도 실측 포함, Gemini 호출 없음)
```

키는 예전과 같다: `GEMINI_API_KEY` 환경 변수 → `gemini_key.txt` → `api_key.txt`.

### 주요 환경 변수 (모두 `vibecut/settings.py` 한 곳에서 읽는다)

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `VIBECUT_AI_MODE` | 키가 있으면 `live` | `offline`이면 네트워크를 쓰지 않는다. 저장해 둔 AI 응답이 있으면 재생, 없으면 규칙 판단 |
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash` / `gemini-3.5-flash-lite` | 글 판단 (혼잡·한도 초과면 대체 모델) |
| `GEMINI_STT_MODEL` / `SCENE_MODEL` | `gemini-3.5-transcribe` / `gemini-3.5-flash-lite` | 받아쓰기 / 영상 장면 이해 |
| `STT_ENGINE` | `auto` | `gemini` → `whisper-local` → `energy`(말소리 구간만) 순서로 대체 |
| `SCENE_ENGINE` | `auto` | `gemini` 또는 `local`(화면 변화 감지) |
| `WHISPER_MODEL` | `small` | 로컬 Whisper 크기 |
| `VIBECUT_DATA_DIR` | `./data` | 프로젝트·작업·캐시 폴더 |
| `VIBECUT_HOST` / `VIBECUT_PORT` | `127.0.0.1` / `8000` | 같은 네트워크에 열려면 HOST를 `0.0.0.0`으로 (인증이 없으니 주의) |

시연 전에 live로 한 번 돌려 두면 AI 응답이 `data/cache/ai`에 저장되고, 발표장에서는 `VIBECUT_AI_MODE=offline`으로 같은 결과를 네트워크 없이 재생할 수 있다.

---

## 2. 구조

```
[브라우저] static/index.html + css/app.css + js/*.js (ES 모듈)
     │  js/api.js (REST + 작업 상태 폴링)
[app.py] → vibecut/server/app.py (FastAPI)
     ├─ server/api.py       REST API (/api/…)
     ├─ server/jobs.py      작업 큐: 디스크 기록, 종류별 동시 실행 제한, 취소, 재시작 복구
     ├─ server/storage.py   프로젝트 저장소 (data/projects/{id}/)
     └─ server/pipeline.py  분석·렌더·프록시 작업 내용
vibecut/
  models.py      데이터 계약 (EditPlan, Line, Scene, TreeNode, StyleSpec, Job …)
  settings.py    환경 변수 → 설정 (모델 이름은 여기 한 곳)
  media/ffmpeg.py   ffmpeg 찾기·실행·진행률·취소, ffprobe 없이 정보 읽기, 오디오 추출, 프록시
  ai/gemini.py   Gemini 통합 클라이언트 (타임아웃·재시도·대체 모델·스키마·캐시·사용량)
  ai/stt.py      받아쓰기 엔진 선택·대체 (엔진 코드는 transcriber.py)
  ai/scenes.py   장면 분석 (Gemini는 scene_analyzer.py, 대체는 화면 변화 감지)
  ai/tree.py     4단 트리 (묶는 규칙은 scene_tree.py)
  ai/judge.py    문장별 컷 판단 (자체 규칙 + Gemini)
  ai/select.py   AI 가편집 (Gemini 점수 + 코드가 분량 맞춤)
  ai/revise.py   채팅 수정 요청
  edit/planner.py  편집 계획 계산 (남길 구간, 단어 경계, 쉼 압축, 프레임 정렬)
  edit/timeline.py 결과 시각 변환, 자막 장면(2줄 나누기·카라오케 단어)
  edit/validate.py 렌더 전 규칙 검사
  render/ass.py    ASS 자막 (PlayRes = 출력 해상도)
  render/fonts.py  글꼴 찾기, CSS px ↔ ASS 크기 변환
  render/compile.py EditPlan → FFmpeg 필터 그래프 하나
  render/renderer.py 렌더 실행 + 결과 길이 검증
  eval/metrics.py  평가 지표
```

`transcriber.py`, `scene_analyzer.py`, `scene_tree.py`, `prompt_builder.py`, `scene_selector.py`, `stt_compare.py`는 **자리를 옮기지 않았다.** 실행 가이드 문서에 적힌 명령(`python transcriber.py --input …` 등)이 그대로 동작하고, 새 패키지가 이 파일들을 불러 쓴다.

### 핵심 계약: EditPlan

```
사용자가 정하는 값                         서버가 계산해 채우는 값 (planner.compile_plan)
  selection  어떤 장면을 쓸지 (all/manual/auto)    keep     남길 구간 [clip_id, 클립 초 start~end, 결과 시작]
  lines      문장별 남김/자름·자막 수정            effects  강조 줌인
  styles     자막·제목·촬영지 자막 스타일          events   결과 영상 위 자막 장면 (결과 초)
  output     16:9/9:16, 해상도, fps                duration 결과 길이
  options    여유·쉼 압축·페이드·음량·자막 켜기     warnings
```

남길 구간과 자막을 분리했기 때문에 **말 없는 장면도 남길 수 있고**(예전엔 자막 문장 구간만 남아 풍경 장면이 항상 잘렸다), clip_id로 **여러 클립**을 자연스럽게 다룬다.

### 시간 기준 세 가지

| 이름 | 기준 | 쓰는 곳 |
| --- | --- | --- |
| 클립 초 | 클립 파일 안 | Line, Scene, KeepRange, Effect |
| 원본 초 | 타임라인 순서로 클립을 이어 붙인 분석용 원본 | TreeNode (장면 트리) |
| 결과 초 | 렌더된 영상 | KeepRange.out_start, SubtitleEvent |

---

## 3. 원칙: LLM은 판단, 코드는 계산·검증

| 단계 | Gemini가 하는 일 | 코드가 하는 일 |
| --- | --- | --- |
| 컷 판단 | 자를 문장·강조 문장을 id로 지목 (이유·확신) | 자체 규칙(지시어·NG 재촬영·군더더기·강조)을 먼저 계산, 응답 병합, 70% 넘게 자르라면 무시 |
| AI 가편집 | 장면별 점수·꼭 넣기·빼기·이유 | 실제로 남는 길이로 목표 ±5% 맞추기 (고정 장면 → 점수순 → 모자라면 좋은 대사) |
| 수정 요청 | 바꿀 문장 id와 keep/text | 모르는 id·과하게 바뀐 글자 버림, 시각은 바꿀 수 없음 |

시각은 절대 LLM에게 돌려받지 않는다. 예전 step3는 Gemini가 시각을 다시 써서 돌려줬고, 들여쓴 JSON은 '복구 로직'이 망가뜨려 AI 판단이 통째로 버려졌다.

---

## 4. 편집 계획 알고리즘 (planner)

```
keep  = 고른 장면 구간의 합집합                     (말 없는 장면 포함)
keep -= 자를 문장 구간 (앞뒤 쉼이 1.5초보다 짧으면 쉼까지)
keep -= 남기는 문장 사이의 긴 쉼 (컷 템포: 느림 1.5초 / 보통 0.8초 / 빠름 0.4초보다 긴 쉼을 0.2초로)
경계  : 장면 경계가 남길 문장 중간이면 문장 끝까지, 단어 안에서 자르지 않음, 근처 무음 쪽으로 이동
여유  : 말 시작 앞 0.08초, 끝 뒤 0.12초. 0.25초보다 짧은 틈은 메우고 0.4초보다 짧은 조각은 버림
정렬  : 클립 프레임 단위로 맞춤 → 영상·소리 조각 길이가 같아 컷이 많아도 싱크 유지
```

## 5. 렌더

구간마다 `trim`/`atrim`으로 프레임 단위로 자르고, 클립 통일(해상도·fps·48kHz 스테레오)·25ms 페이드·강조 줌인·`concat`·자막(libass)·음량(loudnorm)을 **필터 그래프 하나로 처리해 인코딩을 한 번만** 한다.

| 확인 항목 (테스트로 실측) | 결과 |
| --- | --- |
| 키프레임 5초 간격 영상에서 3~6초, 12~14초 남기기 | 예전 media_engine 8.09초 → **5.00초**, 첫 프레임이 정확히 원본 90번 |
| 서로 다른 해상도·fps 클립 + 소리 없는 클립 + 컷 27개 | 영상·소리 길이 차이 0.05초 이내 |
| 결과 길이 − 계획 길이 | +3ms 안팎 |
| 미리보기 캡처 vs 렌더 프레임 자막 영역 (960x540 기준) | 외곽선 스타일 0~3px, 배경 상자 스타일 0~1px 차이 |

자막 크기·여백·두께는 **출력 영상의 짧은 변이 1080px일 때의 px**이다. 화면(`static/js/style.js`)과 서버(`vibecut/render/ass.py`)가 같은 규칙으로 계산하고, 줄바꿈 규칙은 `tests/wrap_cases.json`으로 양쪽을 함께 검사한다.

---

## 6. API 요약

| 요청 | 하는 일 |
| --- | --- |
| `POST /api/projects`, `GET/PATCH/DELETE /api/projects/{id}` | 프로젝트 (이름, 타임라인 순서, 클립 사용 범위) |
| `POST /api/projects/{id}/clips` | 클립 업로드 (여러 개, 1MB씩 저장, 형식 검사) → 540p 프록시 작업 |
| `POST /api/projects/{id}/analyze` → 작업 | 받아쓰기 ∥ 장면 분석 → 컷 판단 → 트리 → 편집 계획 |
| `GET /api/projects/{id}/analysis` | 문장·장면·트리·판단 |
| `GET/PUT /api/projects/{id}/plan`, `PATCH …/plan/lines` | 편집 계획 (계산 결과 + 렌더 전 검사 포함) |
| `POST /api/projects/{id}/select` | 전체 / 직접 고르기 / AI 가편집 |
| `POST /api/projects/{id}/revise` | 채팅 수정 요청 |
| `POST /api/projects/{id}/render` → 작업, `GET …/renders/{파일}` | 미리보기(540p)·최종 렌더, 다운로드 |
| `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel` | 진행률·취소 |
| `GET /api/projects/{id}/metrics`, `GET /api/config` | 평가 지표, 설정·ffmpeg·글꼴 정보 |

예전 엔드포인트(`/upload`, `/analyze`, `/analyze_jobs`, `/render`, `/jobs`, `/media`, `/download`, `/select_scenes`, `/revise`)는 없어졌다. 예전 `uploads/`, `outputs/` 폴더는 더 이상 쓰지 않는다 (필요 없으면 지워도 된다).

---

## 7. 평가 지표 (발표용)

`python -m vibecut.eval.metrics <id>` 또는 내보내기 창.

| 지표 | 뜻 |
| --- | --- |
| 압축률 | 결과 길이 / 원본 길이 |
| 분량 정확도 | 결과 길이 / 목표 분량 (AI 가편집) |
| AI 판단 채택률 | AI·규칙 판단 중 검토에서 사용자가 뒤집지 않은 비율 |
| AI 장면 선택 유지율 | AI가 고른 장면 중 사용자가 그대로 둔 비율 |
| 단어 잘림 | 남길 구간 경계가 단어 중간에 걸린 곳 (0이 정상) |
| 렌더 길이 오차 | 결과 − 계획 (1프레임 33ms 안쪽이 정상) |
| 분석 시간·AI 사용량 | 단계별 시간, 요청 수, 토큰, 캐시 재사용 |

"API만 가져다 쓴 것 아니냐"는 질문에 답할 자체 기술: 무음 기준 단어 경계 보정·환각 필터(transcriber), 문장 재분할, 컷 판단 규칙, 분량 맞춤 선택 알고리즘, EditPlan 계산(단어 경계·쉼 압축·프레임 정렬), 미리보기=렌더 스타일 변환, LLM 출력 검증·부분 대체 계층.

---

## 8. 팀원별로 고칠 곳

| 담당 | 파일 |
| --- | --- |
| 조경우 (영상 이해·트리·평가) | `scene_analyzer.py`, `scene_tree.py`, `vibecut/ai/scenes.py`, `vibecut/ai/select.py`(점수·분량), `vibecut/eval/metrics.py` |
| 권용관 (받아쓰기·백엔드) | `transcriber.py`, `vibecut/ai/stt.py`, `vibecut/server/*`, `vibecut/ai/gemini.py` |
| 신정빈 (화면) | `static/index.html`, `static/css/app.css`, `static/js/*` (편집 설정은 `setup.js`, 스타일 폼은 `stylepanel.js`) |
| 성준규 (편집 실행·렌더·자막) | `vibecut/edit/*`, `vibecut/render/*`, `static/js/style.js`·`preview.js` |

## 9. 알려진 한계

- 로컬 Whisper는 CPU에서 느리다 (medium: 오디오 길이의 약 3~4배). 기본은 Gemini 받아쓰기, Whisper는 대체용
- 화면 변화 감지(오프라인 장면 분석)는 장소·활동 이름을 모른다 → 트리 이름이 `장면 00:00~00:16` 형태
- 아주 짧은 영상은 고를 조각이 커서 목표 분량 ±5%를 못 맞출 수 있다 (가장 가까운 조합을 고르고 경고)
- 인증이 없다. 기본 주소는 이 PC(127.0.0.1)에서만 열린다
- 카라오케는 단어 단위로 색이 바뀐다 (글자가 차오르는 \kf 효과는 쓰지 않음)
