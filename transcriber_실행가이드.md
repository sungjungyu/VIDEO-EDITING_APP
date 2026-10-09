# transcriber.py 실행 가이드 (Windows 노트북 기준)

VIBE CUT 1-2 소리 갈래: 촬영 클립 폴더 → 받아쓰기 JSON(문장 + 단어 시각) + 확인용 표(md)

## 1. 준비 (처음 한 번)

```powershell
# FFmpeg (scene_analyzer와 같음, 설치 후 터미널 다시 열기)
winget install Gyan.FFmpeg

# Whisper (requirements.txt에 포함)
pip install -r requirements.txt
```

- API 키가 필요 없다. 로컬 Whisper로 돌아간다.
- 모델은 처음 실행할 때 `~/.cache/whisper`에 받아진다 (medium 약 1.5GB).

## 2. 실행

```powershell
# 촬영 클립을 한 폴더(raw_clips)에 모은 뒤

# ① 정렬·오디오 추출만 확인 (받아쓰기 안 함)
python transcriber.py --input .\raw_clips --dry-run

# ② 기본 실행: Whisper medium + 무음 기준 단어 경계 보정
python transcriber.py --input .\raw_clips --out transcript.json
```

결과
- `transcript.json`: 받아쓰기 결과 (4단 트리 대사 층의 입력, 자막·카라오케·단어 경계 컷의 입력)
- `transcript.md`: 문장별 표. 확신이 낮은 단어(확률 0.5 미만)를 따로 보여 준다

## 3. 출력 형식

`clips`의 id·offset은 scene_analyzer의 `scenes.json`과 같은 규칙으로 정해진다.
`start`·`end`는 전체 타임라인 초, `clip_start`·`clip_end`는 클립 안 초다.

```json
{
  "meta": {"engine": "whisper-local", "model": "medium", "language": "ko",
           "refine": {"silence_db": -35.0, "min_silence": 0.25}, "elapsed_sec": 115.6, "created_at": "..."},
  "clips": [{"id": "c01", "file": "a.mp4", "duration": 13.17, "offset": 0.0, "has_audio": true}],
  "segments": [
    {"seg_id": "t0001", "clip_id": "c01", "start": 1.12, "end": 9.26, "clip_start": 1.12, "clip_end": 9.26,
     "text": "안녕하세요. 오늘은 …",
     "words": [{"word": "안녕하세요.", "start": 1.12, "end": 1.97, "probability": 0.786}]}
  ],
  "warnings": []
}
```

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
| `--model` | medium (환경변수 `WHISPER_MODEL`) | 개발할 때는 `small`이 빠르다 |
| `--no-refine` | 끔 | 무음 보정 끄기 (보정 전후 비교용) |
| `--silence-db` | -35 | 이보다 작은 소리를 무음으로 본다. 배경 소음이 큰 영상은 -30 등으로 올린다 |
| `--min-silence` | 0.25 | 이보다 짧은 무음은 무시 (초) |
| `--refresh` | 끔 | 받아쓰기 캐시를 무시하고 다시 실행 |

받아쓰기 결과는 `.vibecut_cache/*.stt.json`에 캐시된다. 정리·보정 옵션만 바꿔서 다시 돌리면 Whisper를 다시 실행하지 않는다.

## 5. 동작 요약

1. scene_analyzer의 `collect_inputs`·`probe`로 클립을 모으고 촬영 시각 순으로 정렬, c01… id와 offset 부여
2. FFmpeg로 16kHz 모노 WAV 추출 (오디오 트랙이 없는 클립은 건너뜀)
3. Whisper `word_timestamps=True`로 받아쓰기 (설정은 main.py와 같음)
4. 코드로 정리: 단어 공백 제거, 빈 단어·세그먼트 제거, 0~클립 길이로 자르기, 단어 시각이 줄어들지 않게 맞추기
5. **무음 기준 보정**: FFmpeg `silencedetect`로 무음 구간을 찾아 단어 시작·끝을 무음 경계에 맞춤
6. 전체 타임라인 초로 변환, `seg_id` 부여, 규칙 검사 결과를 `warnings`에 기록

## 6. 왜 무음 보정을 하나

TTS로 만든 테스트 클립(정답 구간을 아는 영상)에서 Whisper medium의 단어 시각을 실제 말소리 구간과 비교했다.

| 문제 | 실측 | 보정 후 |
| --- | --- | --- |
| 첫 단어가 앞 무음까지 포함 | 시작이 최대 1.1초 빠름 | 말 시작과 0.01초 이내 |
| 문장 끝이 뒤 무음까지 포함 | 끝이 최대 0.6초 늦음 | 말 끝과 0.01초 이내 |
| 말 시작보다 늦게 시작 (그대로 자르면 앞소리 잘림) | 0.16~0.22초 늦음 | 말 시작과 0.01초 이내 |

문장 중간의 쉬지 않고 이어지는 단어 경계는 무음이 없어 보정하지 않는다 (Whisper 값 그대로).

## 7. 알려진 한계

- 실제 촬영본(배경 소음, 여러 명이 말하는 장면)으로는 아직 검증하지 않았다. 테스트 원본이 나오면 `--silence-db` 기준을 다시 잡아야 한다.
- 1시간이 넘는 단일 클립의 분할은 아직 없다 (Whisper가 내부적으로 30초씩 처리하므로 동작은 하지만 느림).
- 무음 구간에서 Whisper가 없는 말을 지어내는 현상(환각)은 아직 거르지 않는다.
- 촬영 시각: scene_analyzer `probe()`가 `ffmpeg -v quiet`로 실행돼 메타데이터를 못 읽고 항상 파일 수정 시각을 쓴다. 정렬을 scenes.json과 맞추기 위해 같은 함수를 쓰고 있으므로, scene_analyzer가 고쳐지면 같이 고쳐진다.
