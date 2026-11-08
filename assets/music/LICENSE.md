# 기본 배경음악

앱에 함께 넣어 배포하는 곡입니다. **앱에 넣어 배포해도 되는 라이선스(CC0 등)의 곡만** 둡니다.

## 곡 넣는 방법

1. 음원 파일(mp3 등)을 이 폴더에 둡니다.
2. `tracks.json`에 한 줄 추가합니다.

```json
[
  {"id": "calm-afternoon", "title": "잔잔한 오후", "mood": "잔잔", "file": "calm-afternoon.mp3",
   "source": "FreePD — 곡 이름 / 작곡가", "license": "CC0", "url": "https://freepd.com/..."}
]
```

- `mood`는 `잔잔` · `경쾌` · `감성` 중 하나 (장면 분위기에 맞는 곡에 화면에서 ⭐추천이 붙습니다)
- 파일이 없는 곡은 화면에 나오지 않습니다
- 무료 음원도 다른 사람이 유튜브 Content ID에 잘못 등록해 둔 경우가 있으니, 고른 곡은 유튜브에 한 번 올려 확인합니다
- 원래 FreePD 주소(freepd.com)는 닫혔으므로 url에는 보관 사본 주소를 적습니다

## 들어 있는 곡

모두 **FreePD**(freepd.com)의 곡으로 **CC0 1.0** (퍼블릭 도메인 기증)이다. FreePD FAQ: "Can I include this music in an
app that generates movies for users? **YES!**" — 사용자 영상을 만드는 앱에 넣어 배포해도 된다.

- FreePD는 2025년에 사이트를 닫았다. 곡은 공개 보관 사본(https://a.ocv.me/pub/stuff/music/freepd/, 원래 사이트의
  안내문과 목록을 그대로 옮겨 둠)에서 2026-11-08에 받았다. CC0는 사이트가 닫혀도 그대로다
- 원본(최대 320kbps, 일부는 표지 그림 포함)을 소리만 128kbps MP3로 다시 인코딩했다 (저장소 용량 약 20MB)
- 보관 사본 목록에 작곡가 이름이 없어 적지 않았다
- 곡 선택은 FreePD 분류(chill·upbeat·romantic)와 제목으로 했다 — 직접 들어 보고 바꿀 것

| id | 화면 제목 | 분위기 | 원래 제목 (FreePD 분류) | 길이 |
| --- | --- | --- | --- | --- |
| kalimba-relaxation | 칼림바 휴식 | 잔잔 | Kalimba Relaxation Music (chill) | 7:08 |
| study-and-relax | 공부하며 쉬기 | 잔잔 | Study and Relax (chill) | 3:43 |
| happy-whistling-ukulele | 휘파람 우쿨렐레 | 경쾌 | Happy Whistling Ukulele (upbeat) | 2:03 |
| city-sunshine | 도시의 햇살 | 경쾌 | City Sunshine (upbeat) | 3:05 |
| lovely-piano-song | 사랑스러운 피아노 | 감성 | Lovely Piano Song (romantic) | 1:36 |
| nostalgic-piano | 그리운 피아노 | 감성 | Nostalgic Piano (romantic) | 3:16 |
