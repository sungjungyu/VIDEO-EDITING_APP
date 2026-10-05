# VIBECUT 현황분석 보고서
> 작성 기준: 실제 코드 직접 독해 (2026-10-01)  
> 코드로 확인함 = ✅ 코드 근거 있음 / 추정 = ⚠️ 코드 미확인, 추론

---

## 1. 한 줄 정의

> **"영상 파일을 받아 Whisper로 음성을 받아쓰고, 그 텍스트를 Gemini에게 JSON으로 넘겨 'cut 여부와 자막 스타일'을 생성한 뒤, MoviePy로 cut=false 구간만 이어 붙이고 PIL 자막 이미지를 합성해 MP4를 출력하는 단일 서버 웹앱"**

---

## 2. 전체 구조와 데이터 흐름

### 2.1 폴더 구조

```
VIDEO-EDITING_APP/
├── app.py          FastAPI 웹서버 (339줄) — HTTP 라우터, Job 관리
├── main.py         VideoEditingPipeline 클래스 (795줄) — 핵심 처리 로직
├── config.py       API 키 로드/저장 (86줄)
├── requirements.txt
├── test_gemini.py  수동 연결 테스트 (실행용 스크립트)
├── tests/
│   └── test_gemini_fallback.py  유닛 테스트 4개
└── static/
    ├── index.html  메인 에디터 UI + 모든 JS 인라인 (약 1800줄)
    ├── editor.html 구버전 UI (사용되지 않음 — / 라우트는 index.html)
    ├── app.js      구버전 JS (index.html에 import 없음 — 데드코드)
    └── app.css     구버전 CSS
```

✅ `app.py:78` — `GET /` 는 `index.html`을 반환, `editor.html`은 미사용  
✅ `app.js`, `app.css`는 index.html에서 참조 없음 → 실질적 데드코드

### 2.2 업로드 → 렌더링 단계별 흐름

```
[브라우저] 영상 드래그/클릭 선택
    │
    ▼ handleFiles() [index.html:951]
    ├─ POST /upload → source_file 토큰 저장
    └─ 로컬 썸네일 생성 (Canvas API, 최대 30장)
    
[클립 선택 후 "AI 분석 시작" 클릭]
    │
    ▼ analyzeSelectedClip() [index.html:1466]
    └─ POST /analyze (file + style 폼 전송)
    
[서버: _analyze_video_with_progress() app.py:130]
    ├─ step1_extract_audio() [main.py:162]
    │   MoviePy → audio.wav (16kHz, mono, PCM)
    ├─ step2_transcribe_audio() [main.py:203]
    │   Whisper.load_model() + transcribe()
    │   → List[{start, end, text}]
    ├─ step2_refine_transcript() [main.py:244]
    │   Gemini 호출: 자막 id+text → 교정된 text
    │   타임스탬프 유지, 실패 시 원본 사용
    └─ step3_analyze_context() [main.py:382]
        Gemini 호출: 세그먼트 JSON → cut/subtitle_color/fontsize 결정
        실패 시 _build_local_commands() 폴백
    
[브라우저] GET /analyze_jobs/{id} 폴링 (1500ms 간격) [index.html:1484]
    └─ 완료 시 showReview() → 검토 단계 진입

[사용자 검토: review 단계]
    ├─ 각 세그먼트 텍스트 수정 가능 (textarea)
    ├─ keep/cut 토글 가능 (버튼)
    └─ "AI 편집 시작" → applyEdits() [index.html:868]
        media.segments 갱신 + 타임라인 반영

[사용자 추가 수정: chat 단계]
    └─ sendAiRequest() [index.html:1521]
        POST /revise → Gemini → 수정된 segments 반환

[렌더링 버튼 클릭]
    ├─ buildRenderPayload() [index.html:1556]
    │   ⚠️ 주의: 첫 번째 분석 완료 클립만 전송 (멀티클립 미지원)
    │   subtitle_color="white", fontsize=36 하드코딩 덮어씌움 [index.html:1561]
    └─ POST /render → GET /jobs/{id} 폴링
    
[서버: _render_video() app.py:249]
    ├─ style_overrides로 color/size/font 덮어씀 [app.py:261-268]
    └─ step5_create_final_video() [main.py:526]
        ├─ cut=false 구간만 subclip → concatenate_videoclips
        ├─ _apply_aspect_ratio() center-crop
        ├─ _create_subtitle_image() PIL로 PNG 생성
        └─ write_videofile() ffmpeg libx264+aac
```

### 2.3 핵심 데이터 구조

**segments (백엔드 내부)**
```python
{
    "start": 0.0,           # Whisper 타임스탬프 (초)
    "end": 3.2,             # Whisper 타임스탬프 (초)
    "text": "안녕하세요",    # Gemini 교정 후 텍스트
    "cut": False,           # Gemini 또는 사용자 결정
    "subtitle_color": "cyan",  # Gemini 결정 (스타일별)
    "fontsize": 32,         # Gemini 결정 (스타일별)
    "font_name": None       # style_overrides에서만 주입 (선택)
}
```

**⚠️ 불일치 주의**: `buildRenderPayload()` [index.html:1561]에서  
`subtitle_color: "white"`, `fontsize: 36`을 **하드코딩으로 덮어씀**.  
Gemini가 분석한 색상/크기 정보는 렌더링에 반영되지 않음.  
실제 렌더 색상/크기는 style_overrides의 SUBTITLE_STYLE에서만 결정.

---

## 3. 기능 목록과 구현 상태

| 기능 | 상태 | 근거 파일 | 깊이 설명 |
|---|---|---|---|
| 영상 업로드 (드래그/클릭) | ✅ 완전 동작 | app.py:104, index.html:951 | MIME 체크, UUID 이름, 500MB 제한 |
| 로컬 썸네일 생성 | ✅ 완전 동작 | index.html:924 | Canvas API, 최대 30프레임 |
| 타임라인 배치 (드래그) | ✅ 완전 동작 | index.html:1039 | 드래그&드롭, 스냅 기능 포함 |
| 타임라인 클립 이동 | ✅ 완전 동작 | index.html:1314-1322 | 마우스 드래그로 위치 변경 |
| 타임라인 트림 (좌우 핸들) | ⚠️ 부분 동작 | index.html:1289 | UI는 동작하나 렌더 시 segment 타임스탬프에만 의존 (트림 정확도 미보장) |
| 타임라인 줌 (Ctrl+휠) | ✅ 완전 동작 | index.html:1349 | PX_PER_SEC 15~400 범위 |
| Whisper 음성인식 | ✅ 완전 동작 | main.py:203 | medium 모델, 한국어, temperature=0 |
| Gemini 자막 교정 | ✅ 완전 동작 | main.py:244 | 타임스탬프 유지, 실패 시 폴백 |
| Gemini 컷 편집 판단 | ✅ 완전 동작 (Gemini 의존) | main.py:382 | Whisper 세그먼트 단위, 텍스트만 입력 |
| 편집 스타일 3종 | ⚠️ 부분 동작 | main.py:396-414 | 프롬프트 텍스트만 다름, 별도 로직 없음 |
| 장르별 편집 스타일 | ❌ 미구현 | — | 코드에 없음 |
| AI 검토 단계 (review) | ✅ 완전 동작 | index.html:821 | 텍스트 수정, keep/cut 토글 가능 |
| 자연어 수정 (/revise) | ⚠️ 부분 동작 | app.py:205, index.html:1521 | cut/text 변경 가능, start/end 변경 불가 |
| 빠른 명령 (챗 버튼) | ✅ 완전 동작 (Gemini 의존) | index.html:709 | 4개 고정 명령 → /revise로 전달 |
| 자막 합성 | ✅ 완전 동작 | main.py:123 | PIL PNG, 하단 중앙, 검은 외곽선 고정 |
| 자막 색상 커스텀 | ✅ 완전 동작 | app.py:263, main.py:158 | color picker → style_overrides |
| 자막 크기 커스텀 | ✅ 완전 동작 | app.py:265, main.py:124 | 슬라이더 → style_overrides |
| 자막 폰트 선택 | ✅ 완전 동작 | app.py:267, main.py:610 | 4종 폰트 매핑 |
| 자막 외곽선 토글 | ❌ 껍데기만 | index.html:593, main.py:158 | UI에 존재하나 백엔드에서 항상 stroke_width=2 고정 |
| 자막 배경 박스 토글 | ❌ 껍데기만 | index.html:608, main.py:151 | UI 존재, 백엔드는 항상 RGBA(0,0,0,160) 배경 고정 |
| 카라오케 효과 | ❌ 껍데기만 | index.html:610 | UI 토글 있으나 백엔드 구현 없음 |
| 페이드 인/아웃 효과 | ❌ 껍데기만 | index.html:615 | UI 토글 있으나 백엔드 구현 없음 |
| 화면비 변환 (16:9/9:16) | ✅ 완전 동작 | main.py:505 | center-crop 방식 |
| 실시간 자막 미리보기 | ✅ 완전 동작 | index.html:1406 | WYSIWYG (색상/폰트/외곽선 반영) |
| 렌더링 (ffmpeg) | ✅ 완전 동작 | main.py:632 | libx264+aac, 24fps |
| 완성 영상 다운로드 | ✅ 완전 동작 | app.py:328 | /download/{filename} |
| 멀티클립 렌더링 | ❌ 미구현 | index.html:1557 | 첫 번째 클립만 처리 |
| 실행취소/다시실행 | ❌ 껍데기만 | index.html:413 | disabled 버튼만 존재 |
| 오디오 탭 | ❌ 껍데기만 | index.html:497 | "준비 중" 플레이스홀더 |
| 텍스트 탭 | ❌ 껍데기만 | index.html:505 | "준비 중" 플레이스홀더 |
| 템플릿 버튼 | ❌ 껍데기만 | index.html:450 | icon-disabled |
| 요소/필터 버튼 | ❌ 껍데기만 | index.html:456 | icon-disabled |
| 객체 패널 탭 (배경/스마트/오디오/애니/속도) | ❌ 껍데기만 | index.html:552-556 | "준비 중" 텍스트만 |
| 개인 맞춤 학습 | ❌ 미구현 | — | 코드에 관련 내용 없음 |

### 3.1 자동 컷 편집 상세

**컷 판단 단위**: Whisper 세그먼트 (phrase/sentence 레벨)  
✅ `main.py:233-239` — Whisper `result["segments"]` 그대로 사용  
**단어 단위 또는 프레임 단위 컷은 지원하지 않음**

**컷 경계 정밀도**:  
- Whisper medium 기준 보통 ±100~300ms 오차  
- 세그먼트 경계에서만 컷 → 문장 중간 컷 불가  
- 후처리 없음 (J/L 컷, 오버랩 트랜지션 등 없음)

**편집 스타일 3종 차이**:  
✅ `main.py:396-414` — 프롬프트 안의 설명 텍스트만 다름. 별도 알고리즘 없음  
**결과적으로 스타일별 차이는 Gemini 해석에 100% 의존**  

폴백 시 (`_build_local_commands`, main.py:306):  
- 색상/크기: 스타일별 고정값 적용 ✅  
- cut 판단: `duration < 1.2초 OR len(text) < 6자` 단순 규칙 ✅  
- 이 정도가 팀이 직접 구현한 유일한 편집 판단 로직

---

## 4. 기술 깊이 평가

### 4.1 각 AI 컴포넌트 등급

| 컴포넌트 | 등급 | 근거 |
|---|---|---|
| Whisper 음성인식 | **B** | API 호출 + 파라미터 최적화 (temperature=0, beam_size=5, initial_prompt 설계) + 16kHz 모노 전처리 |
| Gemini 자막 교정 | **B** | 역할 프롬프트 설계 + id 기반 매핑 + timestamp 보존 로직 + JSON 유효성 검사 |
| Gemini 컷 판단 | **A~B** | 스타일별 프롬프트 작성은 B이나 실제 입력은 텍스트뿐 — 오디오/화면 정보 없음 |
| Gemini 자연어 수정 | **A~B** | 프롬프트에 규칙(start/end 변경 금지 등) 명시는 B, 로직 자체는 단순 위임 |
| 폴백 로직 | **C** | `_build_local_commands` — duration/text 길이 기반 규칙 (자체 알고리즘) |
| 자막 렌더링 | **C** | PIL로 직접 구현, ImageMagick 제거, 폰트 폴백 체인 설계 |
| 타임라인 UI | **C** | 바닐라 JS로 드래그/트림/줌/스냅/플레이헤드 직접 구현 |

**등급 기준**: A=API 단순 호출, B=프롬프트 설계+후처리, C=자체 알고리즘, D=자체 학습 모델

### 4.2 Gemini에 주는 입력 전문

**자막 교정** (`main.py:254-263`):
```
텍스트 입력: [{"id": 0, "text": "..."}, ...]
오디오: ❌ 없음
영상 프레임: ❌ 없음
```

**컷 판단** (`main.py:417-444`):
```
텍스트 입력: Whisper 세그먼트 JSON 전체 (start, end, text)
오디오: ❌ 없음
영상 프레임: ❌ 없음
```

**영상 화면을 보는 부분은 코드 전체에 없음** ✅ 확인

### 4.3 심사 질문 "API 가져다 쓴 수준 아니냐"에 대한 답변

**그렇다고 말할 수 있는 부분:**
- 컷 편집 판단 = Gemini에 텍스트 넘기고 결과 받기 (A등급)
- 음성인식 = Whisper.transcribe() 호출 (A등급)
- 두 API 없으면 핵심 기능 전무

**그렇지 않다고 말할 수 있는 부분:**
- **자체 폴백 알고리즘** (`_build_local_commands`, main.py:306): API 없이도 규칙 기반 편집 동작
- **PIL 자막 렌더링** (`_create_subtitle_image`, main.py:123): ImageMagick 대신 직접 구현, 폰트 폴백 체인
- **비동기 Job 파이프라인**: 단계별 진행률 반환, 타임아웃 처리, 예외 격리
- **JSON 복구 로직** (main.py:470-495): Gemini 불완전 응답 파싱 처리
- **바닐라 JS 타임라인**: 드래그/트림/줌/스냅/플레이헤드 직접 구현 (~600줄)
- **WYSIWYG 자막 미리보기**: 렌더 크기 기준 스케일링 (index.html:1428)

**결론**: 핵심 판단 로직은 API 위임이지만, 전체를 연결하는 파이프라인 설계, 예외 처리, UI 구현에서 자체 기술을 확인할 수 있다.

---

## 5. 품질과 한계

### 5.1 테스트 범위

| 구분 | 내용 |
|---|---|
| 유닛 테스트 | 4개 (tests/test_gemini_fallback.py) — 폴백 동작, timestamp 보존만 커버 |
| 통합 테스트 | 없음 |
| E2E 테스트 | 없음 |
| UI 테스트 | 없음 |
| 실제 영상 테스트 | 실행 불가 (샘플 영상 없음, GPU 환경 미확인) |

> ⚠️ **실제 실행 결과 확인 불가**: 분석 중 실제 영상 처리는 시도하지 않았음

### 5.2 심각한 버그: verify_gemini_connection 없음

✅ `app.py:96` — `pipeline.verify_gemini_connection()` 호출  
✅ `main.py:47-795` — `verify_gemini_connection` 메서드 존재하지 않음  
→ **모든 분석 시작 시 AttributeError 발생, `except Exception`에서 묵살됨**  
영향: 로그에 오류 출력되지만 동작 자체는 계속됨. 연결 사전 검증 목적 완전 무효화.

### 5.3 자막 미리보기 ↔ 실제 렌더 불일치

| 옵션 | 미리보기 (JS) | 실제 렌더 (Python) |
|---|---|---|
| 색상 | ✅ 반영 | ✅ 반영 |
| 크기 | ✅ 반영 | ✅ 반영 |
| 폰트 | ✅ 반영 | ✅ 반영 |
| 외곽선 ON/OFF | ✅ 반영 | ❌ 항상 stroke_width=2 |
| 배경 박스 ON/OFF | ✅ 반영 | ❌ 항상 RGBA(0,0,0,160) |
| 카라오케 | UI만 존재 | ❌ 미구현 |
| 페이드 | UI만 존재 | ❌ 미구현 |

> 결과: 사용자가 보는 미리보기와 실제 출력물이 다름. WYSIWYG 아님.

### 5.4 buildRenderPayload 하드코딩 문제

✅ `index.html:1561` — 세그먼트를 렌더 페이로드로 변환할 때  
`subtitle_color: "white"`, `fontsize: 36`으로 **덮어씌움**  
Gemini가 분석해 준 색상/크기 정보 폐기됨.  
실제 자막 스타일은 style_overrides에서만 결정.

### 5.5 멀티클립 미지원

✅ `index.html:1557` — `timelineClips().find(...)` — 첫 번째 클립만  
타임라인에 여러 클립을 배치해도 첫 번째만 렌더링됨.  
UI는 멀티클립을 지원하는 것처럼 보이지만 실제 렌더는 단일 클립.

### 5.6 예상 처리 속도 (10분 영상, CPU 환경 추정)

| 단계 | 예상 시간 | 비고 |
|---|---|---|
| 오디오 추출 | 30~60초 | MoviePy I/O |
| Whisper medium | 3~8분 | CPU 추론 (GPU면 1~2분) |
| Gemini 교정 | 5~15초 | API 왕복 |
| Gemini 컷 판단 | 10~30초 | API 왕복 |
| 렌더링 | 3~8분 | ffmpeg libx264 fast |
| **합계** | **약 7~17분** | Whisper + 렌더링이 병목 |

> ⚠️ 추정값: 실제 실행 미확인

### 5.7 편집 오류 예상 유형 (코드 구조상)

1. **문장 중간 잘림**: Whisper가 세그먼트를 문장 도중에 자를 수 있음 (beam_size=5로 완화되나 완전 방지 불가)
2. **침묵 구간 보존**: Gemini는 텍스트만 보므로 1초 이상 무음 구간을 cut 처리 못할 수 있음 (오디오 정보 없음)
3. **연속 발화 끊김**: keep 구간이 concatenate될 때 오디오 팝/클릭 발생 가능 (페이드 처리 없음)
4. **자막 오버런**: 세그먼트 타임스탬프 기준으로 자막 표시 → cut 구간 제거 후 타임라인이 재조정되지 않으면 자막 타이밍 밀림
5. **폰트 없음 경고**: Windows에서 Nanum 계열 폰트 미설치 시 맑은고딕으로 폴백됨 (실제 영향 없음)

### 5.8 기술 부채

| 항목 | 위치 | 심각도 |
|---|---|---|
| `verify_gemini_connection` 없는 메서드 호출 | app.py:96 | 중간 (현재 묵살됨) |
| `_build_dummy_commands` 데드코드 | main.py:292 | 낮음 |
| `editor.html`, `app.js`, `app.css` 데드코드 | static/ | 낮음 |
| 인메모리 Job 저장 (서버 재시작 시 소실) | app.py:40-42 | 높음 |
| 인증 없음 (모든 엔드포인트 공개) | app.py 전체 | 높음 |
| API 키 평문 파일 저장 | config.py:14 | 높음 |
| 업로드/출력 파일 정리 없음 (무한 누적) | app.py:34-35 | 중간 |
| 동시성 미고려 (단일 프로세스 + 블로킹 pipeline) | app.py:189,303 | 높음 |

---

## 6. 확장 지점

### 6.1 새 기능을 끼워 넣기 좋은 위치

| 기능 | 삽입 위치 | 이유 |
|---|---|---|
| 편집 결과 검수 단계 강화 | `showReview()` → `applyEdits()` 사이 | 이미 review 단계 UI 존재, 세그먼트 배열 조작 지점이 명확 |
| 대안 편집안 생성 (A/B) | `step3_analyze_context()` 반환 후 | 프롬프트를 다르게 해서 2회 호출, 각 결과를 별 탭으로 제시 가능 |
| 화면 기반 판단 (Gemini Vision) | `step3_analyze_context()` 내부 | 프레임 추출 + 멀티모달 입력 추가 — 현재 텍스트 전용과 병렬 처리 가능 |
| 무음 감지 알고리즘 | `step2_transcribe_audio()` 이후 | Whisper 세그먼트 사이 공백을 직접 분석해 silent segment 주입 |
| 트랜지션/페이드 | `step5_create_final_video()` — concatenate 전후 | MoviePy `crossfadein`, `audio_fadeout` 삽입 지점 이미 명확 |

### 6.2 현재 구조에서 확장이 어려운 부분

- **멀티클립 렌더링**: `step5_create_final_video()`는 단일 input_path 설계 → 다중 클립을 받으려면 파이프라인 전면 재설계 필요
- **실시간 진행률**: `asyncio.to_thread`로 스레드 실행 중 세부 단계 보고가 어려움 (현재 5단계 고정) → WebSocket으로 전환 필요
- **개인화 학습**: 세그먼트 결과를 사용자 피드백으로 저장하는 코드 자체가 없음 → DB 레이어 전무

### 6.3 버려도 되는 부분

| 파일/코드 | 이유 |
|---|---|
| `static/editor.html` | index.html로 완전히 대체됨, 라우트 없음 |
| `static/app.js`, `app.css` | index.html에서 참조 없음 |
| `_build_dummy_commands()` (main.py:292) | `_build_local_commands()`로 대체됨, 호출 없음 |
| `test_gemini.py` | 수동 실행 스크립트, 유닛 테스트 아님 |

---

## 7. 최종 요약

### "VIBE CUT은 현재 어디까지 만들어진 무슨 수준의 프로그램인가"

> **VIBE CUT은 현재 "Whisper+Gemini 파이프라인을 FastAPI로 연결한 단일 클립 자동 컷 편집 MVP"까지 만들어진 수준이다.**  
> 업로드 → 분석 → 자막 생성 → 컷 편집 → 검토 → 렌더링의 전체 흐름은 동작하지만, 자막 스타일 옵션 절반이 껍데기이고, 멀티클립을 지원하지 않으며, 핵심 판단 로직은 Gemini API에 텍스트만 던지는 수준이다.

---

### 강점 3개

1. **파이프라인 설계 완성도**  
   업로드~렌더링 전 과정이 비동기 Job 기반으로 연결되고, Gemini 실패 시 폴백까지 구현되어 있음. 에러가 파이프라인 전체를 죽이지 않는 격리 구조.

2. **바닐라 JS 타임라인 직접 구현**  
   드래그&드롭, 클립 이동, 트림 핸들, Ctrl+휠 줌, 스냅, 플레이헤드, WYSIWYG 자막 미리보기를 외부 라이브러리 없이 약 600줄로 구현. 실무적으로 의미 있는 작업량.

3. **ImageMagick 없는 자막 렌더링**  
   PIL로 직접 PNG를 생성해 합성하는 방식으로 환경 의존성 제거. 플랫폼별 폰트 폴백 체인도 현실적으로 설계됨.

---

### 약점 3개

1. **핵심 편집 판단 = 텍스트만 입력한 Gemini 위임**  
   "AI 기반 문맥 감지형 자동 편집"이라고 하지만 오디오 파형, 화면 장면 전환, 비언어적 정보는 전혀 사용하지 않음. 텍스트 내용만 보고 판단하므로 무음 구간이나 반응 씬을 올바르게 처리할 수 없음.

2. **UI와 실제 렌더 불일치 (WYSIWYG 실패)**  
   외곽선 토글, 배경 박스, 카라오케, 페이드가 미리보기에서는 보이지만 렌더링에는 적용되지 않음. 사용자 기대와 출력물이 다름.

3. **싱글 클립 한계 + 핵심 데이터 인메모리 저장**  
   멀티클립 렌더링 미지원, 서버 재시작 시 모든 작업 소실, 동시 요청 처리 불가. 실사용 환경에서 신뢰성 부족.

---

### 캡스톤 심사 기준별 현재 상태

| 심사 기준 | 내세울 수 있는 것 | 내세울 수 없는 것 |
|---|---|---|
| **창의성** | AI 검토 단계(사용자 개입) + Gemini 폴백 설계, WYSIWYG 미리보기 | 오디오/화면 기반 판단 없음, 스타일 차이가 프롬프트 텍스트뿐 |
| **난이도** | Whisper+Gemini+FastAPI+MoviePy 파이프라인 통합, 바닐라 JS 타임라인 | 핵심 AI 로직 = 텍스트 API 호출, 껍데기 기능 다수 |
| **기대효과** | 실제 동작하는 자동 편집 흐름 시연 가능, 한국어 특화 자막 생성 | 실서비스 적합성 부족(보안/확장성 전무), 편집 품질 검증 미흡 |

**종합 조언**: 심사에서 "API 갖다 쓴 것 아니냐"는 질문을 받는다면, 폴백 알고리즘, PIL 자막 파이프라인, 타임라인 UI 직접 구현을 근거로 제시하되, "텍스트만 보는 현재 한계를 인식하고 있으며 캡스톤2에서 무음 감지/장면 전환 탐지 등 오디오·영상 기반 판단을 추가할 것"이라는 명확한 확장 계획을 함께 제시하는 것이 유리함.
