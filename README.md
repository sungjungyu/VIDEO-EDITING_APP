# VIBE CUT

촬영 원본을 올리면 Gemini가 대사와 화면을 분석해 **4단 트리**(장소·세션 → 행동 흐름 → 세부 행동 → 장면)로 정리하고,
고른 장면으로 컷 편집·자막을 입힌 영상을 만들어 주는 웹 앱입니다.

## 준비물

| 항목 | 내용 |
| --- | --- |
| Python | **3.10 이상** (확인한 버전: 3.13.7). 3.9 이하는 실행되지 않습니다 |
| FFmpeg | `ffmpeg`와 `ffprobe` 둘 다 필요. pip로는 설치되지 않습니다 |
| Gemini API 키 | [Google AI Studio](https://aistudio.google.com/app/apikey)에서 발급 |

## 설치 (처음 한 번)

### 1. FFmpeg

```powershell
# Windows (설치 후 터미널을 닫았다가 다시 연다)
winget install Gyan.FFmpeg
```

```bash
# macOS
brew install ffmpeg
```

설치 확인: `ffmpeg -version`, `ffprobe -version`. 없으면 분석은 되어도 **내보내기(렌더)가 실패**합니다.

### 2. 파이썬 패키지

다른 프로젝트와 버전이 섞이지 않도록 가상환경을 권장합니다.

```powershell
# Windows (PowerShell)
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

로컬 Whisper(openai-whisper, torch)는 기본 설치에 들어 있지 않습니다. 받아쓰기는 Gemini로 하므로 필요 없습니다 (아래「선택: 로컬 Whisper」).

## API 키 설정

둘 중 하나만 하면 됩니다. 둘 다 있으면 환경 변수를 먼저 씁니다.

**방법 1 (권장): 파일**

프로젝트 폴더(`app.py`가 있는 폴더)에 `gemini_key.txt`를 만들고 키 한 줄만 넣습니다.

```
AIza로 시작하는 키
```

- 파일 이름은 정확히 `gemini_key.txt`입니다.
- `.gitignore`에 들어 있어 GitHub에 올라가지 않습니다. 키를 커밋하거나 채팅에 붙여 넣지 마세요.

**방법 2: 환경 변수** (그 터미널을 닫으면 사라집니다)

```powershell
$env:GEMINI_API_KEY="발급받은_키"      # Windows PowerShell
```

```bash
export GEMINI_API_KEY="발급받은_키"    # macOS
```

**키 확인** (실제 API를 1번 호출합니다)

```
python tests/test_gemini.py
```

키가 없어도 앱은 켜집니다. 대신「AI 분석 시작」을 누르면
`분석 실패: Gemini API 키가 설정되지 않았습니다…`가 표시됩니다.

## 실행

```
python app.py
```

브라우저에서 http://localhost:8000 을 엽니다.

1. **영상 추가**: 영상을 끌어다 놓거나 클릭해서 올린다.
2. **AI 분석 시작**: 받아쓰기와 장면 분석을 동시에 하고, 4단 트리를 만든다 (1분 47초 영상 기준 약 2분).
3. **편집 설정**: 왼쪽 아이콘. 4단 트리를 펼치거나 접으며 쓸 장면을 체크하거나, 요청 글을 쓰고「AI 가편집하기」를 누른다.
4. **내보내기**: 고른 구간으로 영상을 만든다.

## 테스트

```
python -m unittest discover -s tests
```

실제 API를 부르지 않는 테스트입니다 (현재 95개). `tests/test_gemini.py`는 자동으로 실행되지 않는 키 확인용 스크립트입니다.

## 선택: 로컬 Whisper

인터넷 없이 받아쓰기를 해야 할 때만 씁니다. 느리고(CPU에서 오디오 길이의 약 3~4배) 문장을 빠뜨리는 경우가 있어 예비용입니다.

```
pip install openai-whisper torch
```

- 앱: 실행 전에 환경 변수 `STT_ENGINE=whisper-local`
- 명령줄: `python transcriber.py --input .\raw_clips --engine whisper-local`
- 모델(medium 약 1.5GB)은 처음 실행할 때 받아집니다.

## 문제 해결

| 증상 | 원인과 해결 |
| --- | --- |
| `ModuleNotFoundError` | 가상환경을 켰는지 확인하고 `pip install -r requirements.txt` |
| 실행하자마자 `TypeError: unsupported operand type(s) for \|` | Python 3.9 이하. 3.10 이상으로 실행 |
| `분석 실패: Gemini API 키가 설정되지 않았습니다` | 위「API 키 설정」. 파일 이름·위치(app.py 옆) 확인 |
| `429` / `RESOURCE_EXHAUSTED` / `사용 한도를 다 썼습니다` | 무료 키의 사용 한도 초과 (Gemini 받아쓰기는 하루 25회). 다음 날 다시 하거나 유료 키 사용 |
| `503` / `UNAVAILABLE` | Gemini 서버 혼잡. 자동으로 다시 시도하고 가벼운 모델로 넘어간다. 계속되면 잠시 후 다시 |
| 「장면 분석 실패, 대사만으로 장면을 나눴습니다」 | 장면 분석 단계만 실패 (대개 한도 초과). 트리는 대사만으로 만들어진다 |
| 「AI 보정·구조화에 실패해 규칙으로 묶었습니다」 | `pip show google-genai`로 버전 확인 (2.3.0 이상 필요). 최신이면 한도 초과·혼잡 |
| 내보내기 실패, 메시지에 `ffprobe` | FFmpeg 설치 확인. 설치 위치가 PATH에 없으면 환경 변수 `FFMPEG_BIN`, `FFPROBE_BIN`에 실행 파일 경로 |
| 렌더된 영상의 자막 한글이 깨짐 (macOS·Linux) | 자막 글꼴 기본값이 Windows용 `Malgun Gothic`. `media_engine/config.py`의 `DEFAULT_FONT`를 설치된 한글 글꼴 이름(`Apple SD Gothic Neo`, `NanumGothic` 등)으로 |
| `영상에 오디오 트랙이 없습니다` | 소리가 들어 있는 영상을 사용 |

## 문서

| 문서 | 내용 |
| --- | --- |
| [VIBECUT_4단트리설명.md](VIBECUT_4단트리설명.md) | 4단 트리가 무엇이고 어떻게 만들어지는지 |
| [scene_tree_실행가이드.md](scene_tree_실행가이드.md) | 4단 트리 명령줄 실행, 규칙, 설정(환경 변수), 실측 |
| [transcriber_실행가이드.md](transcriber_실행가이드.md) | 받아쓰기 명령줄 실행 |
| [scene_analyzer_실행가이드.md](scene_analyzer_실행가이드.md) | 장면 분석(조경우) 명령줄 실행 |
| [prompt_builder_설명.md](prompt_builder_설명.md) | AI 가편집 지시문 조립 |
| [docs/통합테스트_병합기록.md](docs/통합테스트_병합기록.md) | 브랜치 병합·통합 점검 기록, 알려진 한계 |

## 라이선스

MIT License
