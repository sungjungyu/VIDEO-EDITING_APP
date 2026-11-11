# VIBE CUT 통합 로드맵 — 다음 Claude 작업용

> 작성: 2026-11-08 · 기준 결정: 「팀 결정 사항 (11-08)」
> 이 문서는 사용자의 로컬 Claude Code가 이어서 작업하기 위한 지시서다. 단계마다 체크박스를 갱신하고, 새 결정은 맨 아래 「결정 기록」에 한 줄씩 추가한다.

## 0. 작업 규칙

- 답변·문서·커밋 메시지는 한국어.
- **커밋은 요청이 있을 때, 푸시는 명시적으로 요청할 때만.**
- 팀원이 쓴 문서(`docs/archive/`, 실행 가이드 등)는 본문을 고치지 않는다.
- `feature/single-pipeline`의 서버 코드(`src/vibecut/`)를 바꿀 때는 **성준규 합의가 필요하다.** 바꿀 내용을 먼저 정리해 사용자에게 보여 준다.
- 서버 동작이 바뀌면 골든 스냅샷(`tests/regression`)이 알려 준다. 의도한 변경인지 확인한 뒤에만 `VIBECUT_UPDATE_GOLDEN=1`로 갱신한다.
- 유료 Gemini 호출이 많은 작업(1시간 원본 분석 등)은 실행 전에 사용자에게 확인한다.
- "코드 있음"과 "실행 확인"을 구분해 보고한다.

## 1. 결정 사항 (11-08)

| 영역 | 결정 |
| --- | --- |
| 화면 구조 | B안 React (`frontend/`, S1~S5-1 흐름, 상태 머신, 목차 탐색) |
| 디자인 스타일 | A안 `web/css`의 어두운 편집 앱 스타일 (색·글꼴·부품 모양만, 배치는 B안 유지) |
| 서버·편집 엔진 | A안 `feature/single-pipeline` (업로드, 분석, 렌더, 작업 큐, 캐시, 측정) |
| 4단 트리 | 유지. 장소·세션 → 행동 흐름 → 세부 행동 → 장면(+대사) |
| 분량 맞추기 | React의 greedy(`computeAutoCompress`) 대신 A안 동적계획법(`editing/select.py` `fit_duration`)을 L4 장면에 적용 |
| 컷 판단 | 하이브리드(애매한 문장만 Gemini)는 호출 비율과 비용 측정 후 기본값 결정 |
| 평가 | 정답지 채점(T1 전체)은 하지 않음. 자동 측정 숫자 + 의견이 갈린 문장만 확인 + 작업 시간 시연 |
| 끄는 기능 | 배경음악, 점프컷 확대, 목소리 다듬기, 채팅 수정 요청 |

## 2. 현재 상태

| 대상 | 상태 |
| --- | --- |
| `origin/feature/single-pipeline` `5884f8a` | A안 v4. 서버 API 있음, 화면은 `web/`(바닐라 JS). 4단 트리 없음 |
| `origin/feature/frontend-renewal` `ac5ad4c` | React 화면, `api/index.js` 100% mock |
| 로컬 `4009a70` | S4 흰 화면 수정, ErrorBoundary, e2e 2개 — **미푸시** |
| `origin/feature/tree-l4-length` `d015b56` | 4단 트리 개선본 (`scene_tree.py`, `shot_analyzer.py`, 테스트 45개) |
| 로컬 전용 | 1시간 분석 결과(`shots.json`, `tree.json`, `tree.md` 등), `video_splitter.py`, `scene_grouper.py`, stash 1개 |

### A안 서버 API (prefix `/api`)

| 용도 | 요청 |
| --- | --- |
| 프로젝트 | `POST /projects` `{name}`, `GET/PATCH/DELETE /projects/{id}` (`timeline`, 클립 in/out) |
| 클립 | `POST /projects/{id}/clips` (multipart, 필드 이름 `files`, 여러 개), `GET …/clips/{clip_id}/proxy` |
| 분석 | `POST /projects/{id}/analyze` `{profile}` → 작업, `GET /projects/{id}/analysis` |
| 계획 | `GET/PUT /projects/{id}/plan`, `PATCH …/plan/lines` |
| 선택 | `POST /projects/{id}/select` `{mode: all/manual/auto, target_sec, user_prompt, locked_ids, beat_ids, profile}` |
| 렌더 | `POST /projects/{id}/render` `{quality: preview/final}` → 작업, `GET …/renders/{file}` |
| 작업 | `GET /jobs/{id}` (`status, progress, stage, message, error, result, metrics`), `POST /jobs/{id}/cancel` |
| 측정 | `GET /projects/{id}/metrics`, `GET /config` |

`Analysis` = `clips(ClipSpan: clip_id, offset, duration)`, `lines(Line: seg_id, clip_id, start, end, text, words)`, `scenes(Scene: scene_id, clip_id, start, end, place, activity, people, event, mood, summary)`, `beats`, `judgments`.
**주의:** 서버를 켜고 끌 때 올린 영상과 프로젝트가 지워진다(`wipe_media`). 캐시(`data/cache/`)는 남는다.

## 3. 목표 구조

```text
React (frontend/, A안 스타일)
  S1 가져오기 → S2 요청(한 줄) → S3 분석 중 → S4 구조 편집(4단 트리) → S5 렌더 → S5-1 결과
        │ api/index.js (mock → 실제 API 어댑터)
FastAPI (A안 src/vibecut)
  받아쓰기 ∥ 장면 분석 → 컷 판단 → [추가] 4단 트리 → L4 → Beat → DP 선택 → EditPlan → 렌더
```

## 4. 단계별 작업

### Phase 0. 준비 (11-08~09)

- [x] `4009a70` 푸시 여부를 사용자에게 확인하고, 요청하면 푸시 → `origin/feature/frontend-renewal`에 푸시됨
- [x] stash(`yonggwan-test` WIP) 내용을 보여 주고 처리 방법 확인 → 로컬 `backup/yonggwan-test-wip` `b415882`(app.py·main.py), 푸시 안 함
- [x] 로컬 전용 1시간 결과 파일을 `data/` 아래 git 제외 폴더로 백업할지 확인 → `local_results/1h_20261103/` (`data/`는 `wipe_media` 때문에 쓰지 않음)
- [x] `feature/single-pipeline`에서 통합 브랜치 생성 (`feature/react-integration`, 기준 `origin/feature/single-pipeline` `5884f8a`)
- [x] `git checkout origin/feature/frontend-renewal -- frontend` 후 `4009a70`의 변경도 반영 (+ "처음으로" 버튼)
- [x] 서버 실행 확인: `.venv`(Python 3.14) `pip install -e ".[dev]"` → `pytest -q` 155개 통과 → `vibecut serve` (11-10)
- [x] React 실행 확인: `cd frontend && npm install && npm run dev` (Vite가 `/api`를 8000번으로 프록시)

완료 기준: 서버와 React가 동시에 켜지고, React에서 `GET /api/config` 응답을 받는다. → **달성 (11-10)**

### Phase 1. 실제 영상으로 S1→S3 (11-12 교수님 미팅까지)

- [x] `frontend/src/api/`에 실제 API 어댑터 추가 (`mock.js`·`real.js`, `index.js`가 선택). 기본 mock, `npm run dev:real`(`.env.real`의 `VITE_USE_MOCK=false`)이면 실제
- [x] S1: 화면 진입 시 `POST /projects`, 업로드는 `POST …/clips`(`files`), 진행률은 XMLHttpRequest. 순서 변경은 `PATCH /projects/{id}` `timeline` (업로드만으로는 타임라인에 안 들어가서 업로드 뒤 `timeline`도 보냄)
- [x] S2: 한 줄 요청·목표 분량·편집 의도(선택)만 받고, S2-1 대신 "요청 확인" 창. 스타일 패널은 실제 모드에서 숨김
- [x] S3: `POST …/analyze` → `GET /jobs/{id}` 2초 폴링. 서버 단계 5개(오디오 추출 → 받아쓰기·영상 분석 → 컷 판단 → 장면 나누기 → 편집 계획)를 칩에 매핑. 실패 시 `error` 표시. 결과 숫자(장면·문장·자름 제안·AI 요청)는 하단에
- [x] 새로고침 복원: 프로젝트가 404면(서버 재시작으로 삭제) S1로 돌려보내고 안내
- [x] 1시간 원본 측정 → `docs/측정기록.md`. 11-10 1차는 받아쓰기 429로 실패(장면 분석만 유효). 429 원인은 유료 Tier 1 받아쓰기 분당 입력 10,000토큰 한도 → 서버에 한도 대기·재시도 추가 후 재측정: 분석 7.1분, $0.361(장면 분석 포함, 2027년 단가 $0.393), 캐시 재실행 2.9초·$0
- 컷 판단 모델 `gemini-3.5-flash`는 지원 중단되어 `gemini-3.6-flash`로 자동 전달됨. 설정을 3.6(또는 3.8)으로 바꿀지 성준규와 정할 것 (`.env`의 `GEMINI_MODEL`로도 가능)
- 실행 확인 (11-10): `e2e/real_s1_to_s3.spec.js` (`E2E_REAL=1`) — 클립 2개(42초) 업로드 → 분석 완료 50초, Gemini 5회. 같은 영상 재실행 11초(캐시). 404 복원 통과. mock e2e 2개도 통과
- [x] 1시간 원본 1회 실행 (사용자 확인 후): 단계별 시간, Gemini 호출 수·토큰, 비용(3.5 가격), 같은 영상 재실행 시간(캐시)을 기록 → `docs/측정기록.md`

완료 기준: 실제 클립 2개 이상을 올려 분석이 끝나고, S3에 실제 진행 단계가 보인다. 1시간 측정값이 기록된다.
안 되면: 어디까지 됐는지와 남은 일정을 정리해 미팅 자료로 쓴다.

### Phase 2. 4단 트리 + DP 선택 (~11-18)

**먼저 성준규와 합의할 것:** 서버에 트리 단계와 API를 추가하는 것, `SelectRequest`에 제외 목록을 넣는 것.

- [x] 장면 분석 일원화: 트리 입력을 A안 `Analysis.scenes`로 만든다. `shot_analyzer.py`를 따로 부르지 않는다 (Gemini 이중 호출 방지)
  - **문제 (11-10 측정)**: 1시간 원본에서 장면 분석이 영상 전체를 한 번에 보고 **장면 10개**만 돌려줬다(평균 약 6분). 4단 트리 L4 입력으로는 너무 거칠 수 있다. 비트는 511개다.
  - 선택지 (아직 정하지 않음, 실행하지 않음):
    1. **장면 분석 조각 나누기**: 영상을 5~10분 조각으로 나눠 장면 분석을 여러 번 부른다. 장면은 많아지지만 호출·비용이 늘고, 서버 코드 변경이라 성준규 합의가 필요하다.
    2. **장면은 L1~L2 힌트, L4는 비트 묶기**: Gemini 장면은 위 단계(장소·활동) 힌트로만 쓰고, L4는 이미 있는 비트(511개)를 묶어 만든다. 추가 호출이 없다.
    3. **`shot_analyzer` 별도 실행**: 예전처럼 샷 단위 분석을 따로 돌린다. 세밀하지만 Gemini 이중 호출이라 이 항목의 목적과 어긋나고 비용·시간이 는다.
  - 먼저 확인: A안 장면 길이·필드가 `scene_tree.py`의 L4 생성에 충분한지. 부족하면 차이를 보고하고 방법을 사용자와 정한다
  - **11-11 확인·결정**: 장면 10개 + 문장 683개를 그대로 넣어도 `build_units`가 문장 사이 쉼에서 나눠 **L4 173개(15~28초)**. 선택지 1~3 없이 이대로 간다. 빠지는 필드는 `visible_text`(AI 대사 보정에서만 쓰임)뿐
- [~] `tree-l4-length`의 `scene_tree.py` 로직을 `src/vibecut/analysis/` 아래 모듈로 옮기고, 분석 작업 마지막 단계로 연결. 테스트 45개도 이전
  - 11-11: `src/vibecut/analysis/tree/`로 옮김(규칙 트리만, AI 구조화는 `ask` 인자로 남김). 분석 작업에 붙이지 않고 **요청할 때 만들어 캐시**. 브랜치 테스트는 옛 모듈(`prompt_builder`, `transcriber`)에 기대 그대로 못 옮기고 새 테스트 4개로 대신. L4 제목은 첫 대사 앞 20자
- [x] 트리를 `Analysis`에 포함하거나 `GET /projects/{id}/tree` 추가. 시각은 `ClipSpan.offset`으로 원본 초 ↔ 클립 초 변환
- [ ] L4 id를 첫 문장 `seg_id` 기반으로 만들어 재분석해도 유지되게 한다
- [ ] L4 → Beat 변환기: `beat_id`=L4 id, `kind`=대사 있으면 speech 없으면 broll, `clip_id/start/end`(클립 초), `seg_ids`, `place`=L1 장소, `title/summary`=L4
- [ ] 선택 연결
  - 직접 채택: `PUT /plan` `selection {mode: manual, beat_ids: 켜진 L4}`
  - AI 구성: `POST /select {mode: auto, target_sec, user_prompt, locked_ids: must_include L4}` → 결과 `beat_ids`를 트리에 "AI가 고름"으로 표시
  - 제외(`must_exclude`): **현재 `SelectRequest`에 필드가 없음.** `select.py`의 never 처리 경로를 확인하고, 없으면 `excluded_ids` 추가안을 정리
  - React `computeAutoCompress`는 서버 결과로 교체하고, `selection.js`는 표시·토글·잠금에만 사용
  - (11-12 리허설) 지금 S4 "AI로 목표 분량 채우기"는 화면 임시 계산(짧은 장면부터 채움)이고 결과 문구에 그렇게 표시한다
  - [ ] (11-12 리허설) **AI 분량 채우기 설명 창**: 결과를 우선순위별로 보여 주고 닫기 버튼 — ① 필수 채택(꼭 넣기·요청에 명시) ② 비중 반영(요청 비중대로 고름) ③ 시간 때문에 제외(목표 분량 초과) ④ 내용상 불필요해서 제외(AI 판단). 서버 DP 선택(`POST /select`)을 연결할 때 같이 만든다
- [ ] (11-12 리허설) **문장 단위 넣기·빼기, 자막 즉석 수정**: S4 상세 패널 대사 목록에서 문장마다 넣기/빼기·자막 글자 고치기. 서버 `PATCH /projects/{id}/plan/lines`(`LinesPatch`, 문장 `keep`·자막 수정)를 그대로 쓸 수 있는지 검토
- [ ] 트리 품질: L1 장소 모순, L1 경계 오류(야외인데 집 세션) 2건 수정. 가능하면 같은 이동 장면 과분할도 병합
  - **11-11 확인 (1시간 원본, AI 트리)**: 41:00~46:00 구간(실제 화면은 42:30·44:00이 어두운 야외 길거리, 39:00·47:00 이후는 실내)이 L1 "집 (1차 방문)" / L2 "실내 운동 및 잡담 흐름"·"집주인 아저씨와의 대화 흐름" / L3 "동아리 소문 이야기"·"가성비 김치찌개 집 추천"에 들어갔다. 그 구간 L4 23개(40:43~46:20)가 모두 `place='실내 방'`, `action='물건 소개하기'`. 지난주 `shot_analyzer` 트리에서는 "어두운 야외 길거리"로 별도 L1이었다.
  - **원인: 큰 장면 10개.** 서버 장면 분석이 60분을 한 번에 저해상도로 보고 31:54~47:19(15.4분)를 "실내 방 · 물건 소개하기" 한 장면으로 묶었다. L4는 장면의 place·action을 그대로 물려받고, 이 구간 대사(동아리 이야기)에는 장소 단서가 없어 AI 구조화도 바로잡지 못한다. 트리 코드 문제가 아니라 입력(장면 경계·장소)이 거친 것이다.
  - 고칠 방법 (아직 정하지 않음, 실행하지 않음):
    1. **장면 분석을 5~10분 조각으로** (서버 `analysis/scenes`, 성준규 합의 필요): 입력 토큰은 영상 길이에 비례해 거의 같고(1시간 약 $0.076) 출력·호출 수만 는다. 조각마다 장면 경계가 세밀해져 장소 변화를 잡을 가능성이 가장 크다. 조각 사이에 앞 조각 요약을 넘겨 장소 이름을 이어 쓴다.
    2. **긴 장면만 다시 보기** (트리 단계): 5분 넘는 Gemini 장면만 그 구간을 잘라 장면 분석을 한 번 더 부른다. 1시간 원본이면 s003·s007·s008·s009 4개(약 46분). 비용은 1번과 비슷하거나 적고, 문제 구간만 손댄다.
    3. **무료 신호로 의심 구간 표시** (화면 밝기·색 변화, 이미 있는 `clip_quality`·`local_scenes` 재사용): 큰 장면 안에서 밝기가 크게 바뀌는 지점에 L4 경계를 두고 `place`를 "(장소 확인 필요)"로 바꿔 AI 구조화에 힌트로 준다. 0원이지만 장소 이름은 모른다. 1·2번 전 임시책
  - **11-11 확인: 1번은 설정이 아니라 코드 작업.** 장면 분석에 조각 길이 설정(환경 변수·config)이 없다. `SceneOptions`에는 `resolution="low"`, `height=360`, `min_sec=10`만 있고 `describe_scenes`가 클립 전체를 한 번에 보낸다(받아쓰기는 `GeminiSttOptions.chunk_sec=300`이 있음).
    새로 만들 때 바뀌는 파일 (서버, 성준규 합의 필요):
    - `analysis/scenes/gemini.py`: `SceneOptions.chunk_sec` 추가, `describe_scenes`가 조각마다 압축본을 만들어 호출하고 시각에 조각 시작을 더함, 앞 조각 요약·인물을 다음 조각 지시문에 넘김, 조각 경계에서 같은 장소·활동이면 합침
    - `media/convert.py`: `make_lowres`에 시작·길이 인자 (조각만 압축)
    - `analysis/scenes/analyze.py`: 캐시 이름에 조각 길이를 넣어 지금 캐시와 섞이지 않게
    - `settings.py`: `SCENE_CHUNK_SEC` 환경 변수 (기본 0 = 지금처럼 한 번에, 되돌리기 쉽게)
    - 테스트: 조각 시각 보정·경계 합치기 단위 테스트, 골든 영향 확인
    - 작업량: 코드 약 100~150줄 + 테스트, 반나절. 비용은 1시간 원본 기준 입력 토큰이 거의 같아(약 $0.076) 출력·호출 수만 는다. 조각을 동시에 보내면 시간은 오히려 줄 수 있다
    - 덤으로 볼 것: 저해상도(`low`, 360p, 초당 1장)라 어두운 야외를 실내로 본 것일 수 있다. 조각을 나눌 때 `resolution`도 함께 비교
- [ ] 비교: 같은 원본에서 greedy와 DP의 목표 분량 오차를 기록

완료 기준: 실제 분석 결과가 S4 트리에 뜨고, 고정·제외·AI 구성 결과가 목표 ±5% 안에 든다.

### Phase 3. 입력 정리 + 디자인 + 렌더 (~11-22)

- [ ] 입력 위치 이동 (교수님 피드백: 첫 화면 입력 줄이기)

| 입력 | 위치 |
| --- | --- |
| 영상, 한 줄 요청 | S1·S2 (필수) |
| 목표 분량 | S2 또는 S4 진입 시 |
| 장면 비중 ("밥 먹기 50%") | S4 "AI로 구성하기" 누를 때 |
| 자막 스타일 | S5-1 "스타일 바꾸기" |
| 비율 | 자동(A안 `auto_aspect`), S5-1에서만 변경 |
| 화질 | 내보내기 단계. `OutputSpec`의 해상도 옵션 확인 후 연결 |

- [ ] (11-12 리허설) **스타일 창 고칠 것** (S5-1 "스타일만 바꾸기")
  - 자막 미리보기가 옆 칸(글꼴·색 입력)을 가린다
  - 색 값 입력칸이 바뀌지 않는다 (지금 `readOnly` + `defaultValue`)
  - 색 고르기는 색 팔레트(`input type=color`)로
  - 글꼴 목록은 `/api/config`의 `fonts`(서버가 렌더할 수 있는 글꼴)를 쓴다
- [ ] (11-12 리허설) **렌더·결과·내보내기 연결**: 지금 실제 모드는 S4 "렌더 →"에서 "렌더 연결은 11/22 예정" 안내만, S5·S5-1은 연결 예정 화면(예시 데이터 숨김). 서버 `POST /render`·작업 폴링·결과 다운로드(MP4·SRT·편집 지시서)로 S5·S5-1을 실제 데이터로
- [ ] 디자인: A안 `web/css/base.css` 팔레트(`--bg #0F1318`, `--panel`, `--border`, `--text`, `--muted`, `--accent`, `--keep`, `--cut`, `--ok`, `--warn`)를 B안 `tokens.css` 변수에 매핑. 버튼·스위치·선택 버튼·입력·진행 막대 스타일 이전
  - 순서: S4 먼저 → 사용자 확인 → 나머지 화면
  - 강조색(보라 vs 파랑)은 S4 시안에서 사용자가 결정
  - 이모지 아이콘, 과한 배지, 그라데이션 줄이기
- [ ] S5: `POST …/render {quality}` → 작업 폴링 → S5-1에서 `GET …/renders/{file}` 재생·다운로드
- [ ] 끄는 기능 확인: `PlanOptions`·`MusicSpec` 기본값에서 배경음악, 점프컷 확대, 목소리 다듬기가 꺼져 있는지 확인하고, 아니면 React 요청에서 끈다

완료 기준: 업로드부터 다운로드까지 React에서 끊김 없이 동작하고, 화면이 A안 스타일로 통일된다.

### Phase 4. 포스터 자료 (~11-25 제출)

- [ ] 측정 표: 1시간 원본 처리 시간·비용, 캐시 재실행, 하이브리드 Gemini 호출 비율(`VIBECUT_JUDGE_MODE=hybrid` vs `all`), greedy vs DP 분량 오차, 단어 잘림 수, 렌더 길이 오차
- [ ] 비용 최적화 설명: 저해상도·1초 1장 분석, 저가 모델, 애매한 문장만 질문, 캐시, 결과만 고화질 렌더
- [ ] (선택) 하이브리드와 Gemini 전체 판단이 다른 문장만 모아 사람이 확인
- [ ] (선택) 10분 영상 수동 편집 vs VIBE CUT 작업 시간 1회 비교
- [ ] 화면 캡처 (S1~S5-1, A안 스타일)

### Phase 5. 시연 준비 (~12-04, 12-01쯤 기능 동결)

- [ ] 시연 영상으로 live 실행해 캐시 생성 → 시연장에서는 `VIBECUT_AI_MODE=offline`으로 재생
- [ ] 팀원 노트북 1대에 처음부터 설치해 전체 흐름 확인
- [ ] 오류 시 대처 메모 (서버 재시작 시 프로젝트 삭제됨 등)

## 5. 하지 않는 것

정답지 채점 전체(T1 bench 운영), 4단 트리를 평평한 목록으로 바꾸기, 배경음악·점프컷·목소리, 채팅 수정 요청, 흔들림 기반 B롤 자동 삽입, 9:16 리프레이밍, 쇼츠 여러 개, AI 모델 학습.

## 6. 미정 사항

- 통합 브랜치 이름과 병합 시점
- React를 Vite 프록시로 시연할지, FastAPI가 빌드 결과를 서빙할지
- 강조색
- 하이브리드 컷 판단을 기본값으로 할지 (측정 후)
- 시연용 영상과 출연자 동의

## 7. 결정 기록

| 날짜 | 결정 | 이유 |
| --- | --- | --- |
| 11-08 | 화면 구조 B안 React, 디자인 A안 스타일 | 교수님이 흐름은 인정, 디자인은 장난감 같지 않게 |
| 11-08 | 서버·편집 엔진 A안 | 실제 동작 확보, 새로 만들 필요 없음 |
| 11-08 | 4단 트리 유지 + DP 분량 맞추기 | 목차 탐색이 B안 차별점, DP는 L4 목록에 그대로 적용 가능 |
| 11-08 | 정답지 채점 제외 | 소규모 데이터로 의미 있는 결과가 어렵고 시간 비용이 큼 |
| 11-08 | 마감 편집 기능 제외 | 목표는 편집 전처리 자동화 (교수님 피드백) |
| 11-10 | 통합 브랜치를 `origin/feature/single-pipeline` `5884f8a`(v4) 위로 다시 만듦 | 처음 만든 기준점 `9395235`에 v4 커밋 22개(src/vibecut, DP 선택, 골든 테스트)가 없었음 |
| 11-10 | 서버는 `.venv`(Python 3.14)에서 실행 | v4는 Python 3.12 이상 필요, 기본 python은 3.11 |
| 11-10 | React 기본은 mock, `npm run dev:real`이 실제 서버 | 기존 e2e(mock 흐름)를 그대로 유지 |
| 11-10 | Phase 1에서 S4 이후는 mock 트리 유지 | 서버 트리 API는 Phase 2 (성준규 합의 후) |
| 11-10 | 받아쓰기 429는 retryDelay(없으면 60초)만큼 기다렸다 최대 3번 재시도, 실패는 경고로 남김 | 429 원인이 분당 한도(유료 Tier 1, 분당 10,000토큰)였음. 대체 방식으로 넘어가는 동작 변경은 성준규와 결정 |
| 11-11 | 트리 L4는 Gemini 장면 10개 + 문장으로 `build_units`가 나눔(장면 분석 조각 나누기·`shot_analyzer` 없이) | 1시간 원본에서 L4 173개, 15~28초로 충분 |
| 11-11 | 트리는 `GET /projects/{id}/tree`에서 요청할 때 규칙으로 만들고 `tree.json`에 캐시, L4 제목은 첫 대사 앞 20자 | 분석 흐름을 건드리지 않고 미팅 전에 S4에 실제 트리를 띄우기 위해. AI 구조화는 사용자 확인 후 |
| 11-11 | 로드맵을 루트 `VIBE_CUT_로드맵_다음클로드용.md`(git 밖)에서 `docs/VIBE_CUT_로드맵.md`로 옮겨 git에 넣음 | 팀 계획이라 원격에 있어야 함 |
| 11-12 | 실제 모드에서 mock 렌더·결과 화면을 숨기고 "렌더 연결은 11/22 예정" 안내, 자동 채우기는 임시 계산임을 표시 | 리허설 피드백: 실제 모드에서 예시 데이터(과자 언박싱, 민수·경우, outro.mp4)가 보이면 안 됨 |
| 11-12 | S4 상세 패널에서 L4·상위 노드 구간의 proxy 영상 재생, 대사 강조·이동 | 리허설 피드백: 장면을 실제 영상으로 확인해야 고를 수 있음 |
