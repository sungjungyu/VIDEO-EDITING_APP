# VIBE CUT 받아쓰기(STT) 작업 계획서

작성: 권용관 · 2026-10-09
기준: VIBECUT_단계별_담당.md (10/05), 백엔드·미디어엔진·프론트 재설계 v2 기획서, 각 브랜치 최신 코드 (kyeongwoo d954938, user-request-ui d874718, refactor 1d50197)

---

## 1. 결론: STT를 먼저, 4단 트리는 그 다음

| 기준 | STT (1-2 받아쓰기) | 4단 트리 (1-3 구조화) |
| --- | --- | --- |
| 담당표상 담당 | **권용관** | 조경우 |
| 데이터 흐름 | 트리보다 **앞** (1-2 → 1-3) | STT 결과가 있어야 "대사" 층을 만들 수 있음 |
| 현재 상태 | 단일 파일·문장 단위만 있음. **단어 시각 없음, 멀티클립 없음** | 입력 중 장면 목록(scene_analyzer)만 완성 |
| 막고 있는 팀원 | 성준규(단어 경계 컷, 카라오케), 조경우(트리 대사 층), 신정빈(v2 `transcript_words`) | 신정빈은 가짜 트리로 이미 화면을 만들어 둠 → 당장 막힌 사람 없음 |
| 받는 쪽 준비 상태 | `media_engine`(카라오케·시각 재매핑), `backend/routers/render.py`가 이미 `words`를 받도록 구현됨. **만드는 쪽만 비어 있음** | prompt_builder가 어떤 필드명이든 흡수하도록 되어 있음 |
| 일정 | 담당표 "주의": 받아쓰기 실험은 **이번 주(10/05 주) 안 1차 결과** 목표 | 1차 목표는 스키마 합의까지 |

→ STT는 원래 내 담당이고, 트리와 다른 두 명의 작업을 동시에 막고 있다. 트리를 맡게 되더라도 STT 결과가 먼저 있어야 한다.

> 4단 트리는 조경우 담당으로 유지하고, 나는 트리가 바로 쓸 수 있는 형식으로 받아쓰기 결과를 넘겨 주는 것을 제안한다. (팀 회의에서 확인)

---

## 2. 현재 코드에서 확인한 사실

- **만드는 쪽**: `main.py` `step2_transcribe_audio()`
  - 로컬 Whisper medium, `{start, end, text}`만 반환. `word_timestamps` 옵션을 쓰지 않음
  - 파일 1개 기준이라 여러 클립과 전체 타임라인 시각이 없음
- **받는 쪽은 이미 `words`를 기다림**
  - `media_engine/main.py`: `subtitles[].words = [{word, start, end}]` (카라오케용)
  - `media_engine/ass_generator.py`: `_build_karaoke_text()`가 `words`로 `\k` 태그 생성
  - `media_engine/timestamp_mapper.py`: 컷 후 `words` 시각 재계산
  - `backend/routers/render.py`: `WordTimestamp {word, start, end}`
  - 백엔드 기획서 `/edit` 응답, 프론트 v2 `transcript_words`도 같은 형식
- **장면 목록(조경우)과 시각 기준을 맞춰야 함**: `scene_analyzer.py`는 클립을 촬영 시각 순으로 정렬하고 `clip_id`(c01…)와 `offset`을 붙여 **전체 타임라인 초**로 변환한다. 받아쓰기도 같은 정렬·같은 id를 써야 트리에서 둘을 합칠 수 있다.
- **병합 충돌 위험**: `feature/refactor`가 `main.py`를 크게 수정했다 (STT 함수 자체는 건드리지 않음). → STT는 `main.py`를 고치지 않고 **새 모듈로** 만든다.
- **교정 단계 주의**: `step2_refine_transcript()`가 Gemini로 `text`를 고친다. 고친 뒤에는 `text`와 `words`가 서로 안 맞을 수 있다.

---

## 3. 출력 형식 초안 (`transcript.json`)

scene_analyzer의 `scenes.json`과 같은 모양으로 맞춘다. 단어 형식은 media_engine·백엔드와 똑같이 한다.

```json
{
  "meta": {
    "engine": "whisper-local", "model": "medium", "language": "ko",
    "elapsed_sec": 0.0, "created_at": "2026-10-09T00:00:00"
  },
  "clips": [
    { "id": "c01", "file": "IMG_0001.mp4", "duration": 312.4, "offset": 0.0 }
  ],
  "segments": [
    {
      "seg_id": "t0001",
      "clip_id": "c01",
      "start": 12.30, "end": 15.84,
      "clip_start": 12.30, "clip_end": 15.84,
      "text": "안녕하세요 오늘은 카페에 왔어요",
      "words": [
        { "word": "안녕하세요", "start": 12.30, "end": 13.02 },
        { "word": "오늘은",     "start": 13.10, "end": 13.55 }
      ]
    }
  ]
}
```

- `start`·`end`: 전체 타임라인 초. `clip_start`·`clip_end`: 클립 안 초. scene_analyzer와 같은 규칙이다.
- `clips`는 scenes.json과 **같은 id·offset**이 나와야 한다. 정렬 함수를 따로 만들지 않고 scene_analyzer의 `collect_inputs`·`probe`를 가져다 쓴다.
- 미디어엔진·백엔드에는 `segments`에서 `{start, end, text, words}`만 뽑아 넘기는 변환 함수를 함께 제공한다.

---

## 4. 할 일 순서

### Step 0. 준비 (반나절)

- [x] 브랜치: `yonggwan` (kyeongwoo 장면 분석 + user-request prompt_builder 병합 상태에서 시작)
- [ ] API 키: `GEMINI_API_KEY` 환경변수 + `gemini_key.txt`. 비교 실험을 하면 OpenAI 키도 준비
- [ ] 테스트 클립: `raw_clips/`에 한국어 발화가 있는 짧은 클립 2~3개 (각 1~5분, 촬영 시각 다르게)
  - 공통 촬영본(30분~1시간)이 나오기 전까지 임시로 쓴다
- [ ] 정답 자막: 클립 1개에서 1~2분 분량을 직접 받아써 둔다 (정확도 비교 기준)
- [ ] `pip install pytest`

### Step 1. 기준선: 로컬 Whisper + 단어 시각 (1일)

- [ ] 새 파일 `transcriber.py` (main.py는 수정하지 않음)
  - 사용 예: `python transcriber.py --input ./raw_clips --engine whisper-local --out transcript.json`
  - 클립 정렬·offset: scene_analyzer의 함수를 재사용
  - 오디오: FFmpeg로 16kHz 모노 WAV 추출, `.vibecut_cache/`에 캐시
  - Whisper: `transcribe(..., word_timestamps=True)` → `segment["words"]` 사용 (단어 앞 공백 제거)
- [ ] 결과를 3장 형식의 `transcript.json`과 눈으로 보기 쉬운 `transcript.md` 표로 저장
- 완료 기준: 클립 2개 이상 → 단어 시각이 들어간 `transcript.json` 1개

### Step 2. 코드로 검증·정리 (반나절)

엔진 출력을 그대로 믿지 않는다 (scene_analyzer의 `clean_scenes`와 같은 방식).

- [ ] 단어 시각이 계속 커지는지(단조 증가), 세그먼트 범위 안에 있는지 확인
- [ ] 빈 단어 제거, 길이 0이거나 음수인 단어 보정
- [ ] 세그먼트끼리 겹치면 정리
- [ ] `text`와 `words`를 이어 붙인 문장이 일치하는지 검사
- [ ] `tests/test_transcriber.py`: 가짜 Whisper 출력으로 위 규칙을 테스트 (API 없이 실행 가능해야 함)

### Step 3. 엔진 비교 실험 (1일) — 담당표의 "받아쓰기 비교"

| 후보 | 비고 |
| --- | --- |
| 로컬 Whisper (medium / small) | 이미 설치됨, 비용 0. 이 PC는 CPU 전용이라 느림 |
| Whisper API | 계획서 후보. 단어 시각을 주는 모델·옵션은 실험할 때 공식 문서로 확인 |
| Gemini 받아쓰기 | 계획서 후보. LLM이 말한 시각이라 단어 시각 정밀도가 가장 의심스러움 |

- 비교 항목: 글자 오류율(정답 자막 대비), 단어 시각 오차(샘플 20개를 파형이나 재생으로 확인), 처리 시간, 비용
- 산출물: `docs/stt_비교.md` 표 1장 → 팀 회의에서 엔진 결정
- [ ] 엔진 선택을 `--engine` 옵션으로 바꿀 수 있게 구조화

### Step 4. 연결 (반나절)

- [ ] `to_subtitles(transcript)`: 미디어엔진 `subtitles` / 백엔드 `SubtitleItem` 형식으로 변환
- [ ] Gemini 교정과의 관계 결정: (a) 교정은 `text`에만 하고 `words`는 원본 유지, (b) 교정 후 단어 시각 재정렬 중 선택
- [ ] 조경우에게 `transcript.json` 샘플 전달 (트리 대사 층 입력), 성준규에게 `words` 샘플 전달

### 다음 차수 (담당표 2차·3차, 지금은 하지 않음)

- 1시간 넘는 클립: 조각 분할, 겹침, 병합
- 여러 클립 업로드 API, 압축·업로드 병렬 처리 (1-1)
- 선택 모드 API (1-5), 프로필 저장 (2-2), 편집 지시서 JSON (3-1)

---

## 5. 팀원과 맞출 것

| 누구 | 무엇을 |
| --- | --- |
| 조경우 | `transcript.json` 형식 합의, 클립 정렬 함수 공유(scene_analyzer 함수 import 허락), 트리 "대사" 노드를 세그먼트 단위로 할지 문장 단위로 할지 |
| 성준규 | `words` 형식 확인 (media_engine과 같음), 단어 경계 컷에 필요한 시각 정밀도 |
| 신정빈 | v2 기획서의 `transcript_words` 사용 여부와 화면 표시 방식 |
| 전원 | 4단 트리 최종 담당 확인, 테스트 원본 촬영 일정 |

---

## 6. 위험 요소와 대응

| 위험 | 대응 |
| --- | --- |
| CPU 전용 PC라 Whisper medium이 느림 (10분 영상 3~8분) | 개발은 짧은 클립과 small 모델로, 결과는 캐시. 정확도 비교만 medium으로 |
| 한국어 단어 시각이 어절과 정확히 안 맞을 수 있음 | Step 3에서 실제 출력을 확인하고, 필요하면 공백 기준으로 다시 묶기 |
| main.py 병합 충돌 (refactor 브랜치) | STT는 새 모듈로 만들고 main.py에서는 호출만 바꾼다 (나중에) |
| 실제 얼굴·목소리 영상의 API 전송 | 무료 등급은 입력이 학습에 쓰일 수 있음 → 실제 촬영본은 유료 키로 (scene_analyzer 가이드와 동일) |
| 교정 후 text와 words 불일치 | Step 4에서 방식 결정, 검증 함수로 확인 |

---

## 7. 일정 (안)

| 날짜 | 할 일 | 결과물 |
| --- | --- | --- |
| 1일차 | Step 0 + Step 1 | 로컬 Whisper `transcript.json` |
| 2일차 | Step 2 + Step 3 시작 | 검증 코드·테스트, 엔진별 결과 |
| 3일차 | Step 3 마무리 + Step 4 | `docs/stt_비교.md`, 변환 함수, 팀원에게 샘플 전달 |
| 체크포인트 회의 | "받아쓰기 서비스 확정, 단어 타임스탬프 확보" | 담당표 1차 체크포인트 항목 |
