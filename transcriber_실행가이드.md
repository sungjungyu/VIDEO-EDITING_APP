# transcriber.py 실행 가이드 (Windows 노트북 기준)

VIBE CUT 1-2 소리 갈래: 촬영 클립 폴더 → 받아쓰기 JSON(문장 + 단어 시각) + 확인용 표(md)

## 1. 준비 (처음 한 번)

```powershell
# FFmpeg (scene_analyzer와 같음, 설치 후 터미널 다시 열기)
winget install Gyan.FFmpeg

# Whisper (requirements.txt에 포함)
pip install -r requirements.txt
```

엔진은 두 가지다. 비교 결과는 `docs/stt_비교.md`.

| 엔진 | 준비 | 속도 (이 노트북) | 특징 |
| --- | --- | --- | --- |
| `gemini` (권장) | API 키: `GEMINI_API_KEY` 또는 `gemini_key.txt` | 오디오 길이의 약 0.2배 | 단어 시각·문장 단위 제공, 화자 구분 가능. 무료 키는 하루 25회 |
| `whisper-local` (기본값, 예비) | 키 필요 없음. 모델은 처음 실행 때 `~/.cache/whisper`에 받아짐 (medium 약 1.5GB) | 약 3.4배 | 인터넷 없이 동작. 문장을 빼먹거나 무음에서 지어내는 경우가 있음 |

## 2. 실행

```powershell
# 촬영 클립을 한 폴더(raw_clips)에 모은 뒤

# ① 정렬·오디오 추출만 확인 (받아쓰기 안 함)
python transcriber.py --input .\raw_clips --dry-run

# ② Gemini
python transcriber.py --input .\raw_clips --engine gemini --out transcript.json

# ③ 로컬 Whisper (기본값)
python transcriber.py --input .\raw_clips --out transcript.json
```

결과
- `transcript.json`: 받아쓰기 결과 (4단 트리 대사 층의 입력, 자막·카라오케·단어 경계 컷의 입력)
- `transcript.md`: 문장별 표. 확신이 낮은 단어(확률 0.5 미만, Whisper만)를 따로 보여 준다

중간에 실패하면(예: 무료 한도 초과) 어느 클립에서 왜 멈췄는지 한 줄로 알려 준다.
끝난 클립은 캐시에 남으므로 같은 명령을 다시 실행하면 이어서 한다.

## 3. 출력 형식

`clips`의 id·offset은 scene_analyzer의 `scenes.json`과 같은 규칙으로 정해진다.
`start`·`end`는 전체 타임라인 초, `clip_start`·`clip_end`는 클립 안 초다.

```json
{
  "meta": {"engine": "whisper-local", "model": "medium", "language": "ko",
           "refine": {"silence_db": "auto", "min_silence": 0.25}, "elapsed_sec": 115.6, "created_at": "..."},
  "clips": [{"id": "c01", "file": "a.mp4", "duration": 13.17, "offset": 0.0, "has_audio": true, "silence_db": -53.9}],
  "segments": [
    {"seg_id": "t0001", "clip_id": "c01", "start": 1.1, "end": 9.3, "clip_start": 1.1, "clip_end": 9.3,
     "text": "안녕하세요. 오늘은 …",
     "words": [{"word": "안녕하세요.", "start": 1.1, "end": 1.95, "probability": 0.786}]}
  ],
  "dropped": [{"clip_id": "c05", "start": 8.6, "end": 10.0, "text": "한국어 자막은 …", "reason": "안내 문구(initial_prompt) 반복"}],
  "warnings": []
}
```

- `clips[].silence_db`: 그 클립에 실제로 쓴 무음 기준 (자동으로 정한 값)
- `dropped`: 환각 의심으로 뺀 세그먼트와 이유 (시각은 클립 안 초). 잘못 빠진 게 없는지 `transcript.md` 아래 표로 확인한다
- `warnings`: 규칙 검사에서 걸린 문제 (빈 리스트면 통과)

다른 모듈에 넘길 때 (`words`는 media_engine·backend와 같은 `{word, start, end}` 형식):

```python
from transcriber import to_subtitles, validate_transcript

subs = to_subtitles(transcript)                 # 전체 타임라인 초
subs = to_subtitles(transcript, clip_id="c01")  # 한 클립만, 클립 안 초 (현재 단일 클립 렌더용)
problems = validate_transcript(transcript)      # text를 고친 뒤 words와 어긋났는지 등 검사
```

## 4. 옵션

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--engine` | whisper-local | `gemini` 또는 `whisper-local` |
| `--model` | 엔진별 기본값 | whisper-local: medium (환경변수 `WHISPER_MODEL`, 개발할 때는 `small`이 빠름) / gemini: gemini-3.5-transcribe |
| `--vocab` | 없음 | gemini 전용. 고유명사 힌트를 쉼표로 (예: `"성수동,소금빵"`) |
| `--diarize` | 끔 | gemini 전용. 화자 구분 → `segments[].speaker` (예: `spk:0`) |
| `--chunk-sec` | 600 | gemini 전용. 한 번에 보낼 최대 길이. 넘으면 무음 지점에서 나눠 보낸다 (요청 크기 약 20MB 제한) |
| `--initial-prompt` | 자막 안내 문구 | whisper-local 전용 |
| `--no-refine` | 끔 | 무음 보정 끄기 (보정 전후 비교용) |
| `--silence-db` | 자동 | 무음 기준(dB). 안 주면 클립마다 배경 소음을 보고 정한다. 직접 주면 그 값으로 고정 |
| `--min-silence` | 0.25 | 이보다 짧은 무음은 무시 (초) |
| `--keep-hallucinations` | 끔 | 환각 의심 세그먼트를 빼지 않음 (필터 전후 비교용) |
| `--refresh` | 끔 | 받아쓰기 캐시를 무시하고 다시 실행 |

받아쓰기 결과는 `.vibecut_cache/*.stt.json`에 캐시된다. 정리·보정 옵션만 바꿔서 다시 돌리면 Whisper를 다시 실행하지 않는다.

## 5. 동작 요약

1. scene_analyzer의 `collect_inputs`·`probe`로 클립을 모으고 촬영 시각 순으로 정렬, c01… id와 offset 부여
2. FFmpeg로 16kHz 모노 WAV 추출 (오디오 트랙이 없는 클립은 건너뜀)
3. 받아쓰기
   - whisper-local: `word_timestamps=True` (설정은 main.py와 같음)
   - gemini: REST로 `generationConfig.audioTranscriptionConfig`(wordTimestamp, VERBATIM, temperature 0) 요청. 긴 오디오는 `--chunk-sec`마다 무음 지점에서 잘라 FLAC으로 보내고, 단어를 문장부호·1.5초 쉼 기준으로 문장으로 묶는다
     (google-genai SDK 2.13은 응답의 `audioTranscription` 필드를 버려서 SDK 대신 REST를 쓴다)
4. **환각 필터**: 말소리가 없는데 엔진이 지어낸 세그먼트를 뺀다 (아래 7장)
5. 코드로 정리: 단어 공백 제거, 빈 단어·세그먼트 제거, 0~클립 길이로 자르기, 끝 시각 순 정렬, 단어 시각이 줄어들지 않게 맞추기
   (엔진이 문장 첫 단어 시작을 크게 틀리는 경우가 있어 끝 시각으로 정렬한다. 실측: Gemini 10초, Whisper 1.1초)
6. **무음 기준 보정**: 0.05초 단위 음량으로 무음 구간을 찾아 단어 시작·끝을 무음 경계에 맞춤 (아래 6장)
7. 전체 타임라인 초로 변환, `seg_id` 부여, 규칙 검사 결과를 `warnings`에 기록

## 6. 왜 무음 보정을 하나

TTS로 만든 테스트 클립(정답 구간을 아는 영상)에서 Whisper medium의 단어 시각을 실제 말소리 구간과 비교했다.
Whisper는 문장 앞뒤 단어 시각을 크게 틀린다.

| 문제 | 실측 |
| --- | --- |
| 첫 단어가 앞 무음까지 포함 | 시작이 최대 1.1초 빠름 |
| 문장 끝이 뒤 무음까지 포함 | 끝이 최대 0.6초 늦음 |
| 말 시작보다 늦게 시작 (그대로 자르면 앞소리 잘림) | 0.16~0.22초 늦음 |

무음 기준을 -35dB 같은 고정값으로 두면 배경 소음이 있을 때 무음이 쪼개지거나 아예 안 잡힌다.
그래서 클립마다 기준을 자동으로 정한다: 하위 10% 음량을 배경 소음, 상위 10%를 말소리로 보고
`기준 = 소음 + max(6dB, 둘 차이의 30%)`.
단, 기준은 말소리보다 최소 10dB 아래로 제한한다 (쉬는 구간이 10%도 안 되게 계속 말하면 '하위 10%'가 말소리가 되어 전체가 무음으로 잡히는 문제 방지).

문장 경계 오차 (정답 구간 대비, 같은 문장에 배경 소음만 다르게 섞음):

| 클립 | 보정 없음 | 고정 -35dB | 자동 기준 (기본값) |
| --- | --- | --- | --- |
| 깨끗함 | 평균 0.33초 / 최대 1.12초 | 0.00초 | 평균 0.03초 / 최대 0.04초 |
| 약한 소음 (-30dB) | 평균 0.38초 / 최대 1.12초 | 평균 0.36초 / 최대 0.85초 | 평균 0.07초 / 최대 0.30초 |
| 센 소음 (-20dB) | 평균 0.37초 / 최대 1.12초 | 효과 없음 | 평균 0.06초 / 최대 0.28초 |

(깨끗한 클립의 정답 구간은 FFmpeg로 잰 값이라 고정 -35dB가 유리하게 나온다.)
문장 중간의 쉬지 않고 이어지는 단어 경계는 무음이 없어 보정하지 않는다 (Whisper 값 그대로).

## 7. 환각 필터

소음만 있는 10초 클립에서 Whisper가 `initial_prompt` 문구를 섞어 "한국어 자막은 제품명과 단위를 정확히 표기하세요."를
출력했다 (무음 확률 0.59로 Whisper 자체 기준 0.6을 아슬아슬하게 통과, 평균 단어 확률 0.17).
실제 말소리는 센 소음 속에서도 평균 단어 확률 0.93이었다. 다음 중 하나면 뺀다.

- 문장이 `initial_prompt`와 글자 2개 묶음 기준 60% 이상 겹침
- 평균 단어 확률 < 0.4 이면서 무음 확률 ≥ 0.4

"구독과 좋아요" 같은 문구 목록으로 거르지 않는다 (브이로그에서 실제로 하는 말이라).

## 8. 알려진 한계

- 실제 촬영본(배경 소음, 여러 명이 말하는 장면)으로는 아직 검증하지 않았다. 위 수치는 TTS + 인공 소음 기준이다.
- whisper-local 속도 (이 노트북 CPU 기준): medium은 오디오 길이의 약 3.4~4.4배, small은 약 1.6배. 1시간 영상이면 medium 3시간 이상.
- whisper-local은 2분 테스트 클립에서 문장 두 개를 통째로 빼먹었다 (`docs/stt_비교.md`). 예비 엔진으로만 쓴다.
- gemini 무료 키는 하루 25회 (10분 조각 기준 약 4시간 분량). 실제 촬영본(얼굴·목소리)은 유료 키 권장.
- 환각 필터 기준(0.4, 60%)은 테스트 클립 기준이다. 실제 촬영본에서 `dropped`를 보고 다시 잡아야 한다.
- 촬영 시각: scene_analyzer `probe()`가 `ffmpeg -v quiet`로 실행돼 메타데이터를 못 읽고 항상 파일 수정 시각을 쓴다. 정렬을 scenes.json과 맞추기 위해 같은 함수를 쓰고 있으므로, scene_analyzer가 고쳐지면 같이 고쳐진다.
