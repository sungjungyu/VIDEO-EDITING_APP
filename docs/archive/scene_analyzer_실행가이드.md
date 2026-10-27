# scene_analyzer.py 실행 가이드 (Windows 노트북 기준)

VIBE CUT 1-2 화면 갈래: 촬영 클립 폴더 → 장면 목록 JSON + 비교용 표(md)

## 1. 준비 (처음 한 번)

```powershell
# FFmpeg 설치 (설치 후 터미널 다시 열기)
winget install Gyan.FFmpeg

# Gemini SDK (Interactions API를 쓰므로 최신 버전)
pip install -U google-genai

# API 키 (현재 터미널에만 적용)
$env:GEMINI_API_KEY="발급받은_키"
```

API 키: https://aistudio.google.com/apikey
팀원 얼굴이 나온 실제 영상은 유료 등급 키로 돌리는 게 안전하다 (무료 등급은 입력이 구글 제품 개선에 쓰임).

## 2. 실행

```powershell
# 촬영 클립을 한 폴더(raw_clips)에 모은 뒤

# ① 전처리만 확인 (API 호출 없음, 비용 0)
python scene_analyzer.py --input .\raw_clips --dry-run

# ② 기본 실행: Flash-Lite, static, 360p
python scene_analyzer.py --input .\raw_clips --out lite_static.json
```

결과
- `lite_static.json`: 장면 목록 (1-3 구조화의 입력)
- `lite_static.md`: 촬영 일지와 눈으로 비교하기 쉬운 표

## 3. 비교 실험 (설정만 바꿔 여러 번)

| 실험 | 명령 |
| --- | --- |
| 모델 | `--model gemini-3.8-flash --out flash_static.json` |
| 처리 모드 | `--mode agentic --out lite_agentic.json` |
| 해상도 | `--height 720 --out lite_720.json` |
| 장면 최소 길이 | `--min-sec 20 --out lite_min20.json` |

전처리 결과는 `.vibecut_cache`에 저장돼서 두 번째부터는 압축을 건너뛴다.
각 JSON의 `meta.elapsed_sec`(처리 시간)과 `usage`(토큰)로 비용·속도를 비교한다.

## 4. 동작 요약

1. ffprobe로 클립 길이·촬영 시각 읽기 → 시간순 정렬, 전체 타임라인 offset 부여
2. FFmpeg로 360p·초당 1장·무음 압축
3. Gemini File API 업로드 → 장면 분석 → **업로드 파일 즉시 삭제**
4. 이전 클립 요약을 다음 클립 프롬프트에 전달 (클립이 끊겨도 같은 장소 판단)
5. 코드로 검증: 범위 자르기, 정렬, 빈틈·겹침 맞붙이기, 같은 장면·짧은 장면 합치기
6. 클립 시각 → 전체 시각 변환, `scene_id` 부여

## 5. 알려진 한계

- 해상도는 전처리 화질(`--height`)로만 조절한다. API의 `media_resolution` 파라미터는 Interactions API 기준 정확한 이름을 확인한 뒤 추가할 예정 (Gemini 3 영상 기본값은 이미 저해상도).
- JSON 형식 강제(Structured outputs) 대신 프롬프트 + 파싱 + 재시도로 처리한다.
- 클립을 순서대로 하나씩 처리한다 (이전 클립 요약을 넘기기 위해). 1시간 이상인 단일 클립 분할은 아직 없음.
- 실제 API 호출은 이 환경에서 테스트하지 못했다. 처음 돌릴 때 클립 1~2개로 먼저 확인할 것.
