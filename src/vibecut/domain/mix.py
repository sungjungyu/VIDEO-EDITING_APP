"""배경음악 크기 규칙 (v4 설계안 T5). 렌더(render/renderer.py의 ffmpeg 식)와 화면 미리보기(web/js/core/mix.js)가
같은 규칙을 쓴다 — 숫자를 바꾸면 두 곳을 함께 바꾼다 (tests/fixtures/mix_cases.json으로 양쪽을 검사).

    크기(t) = 음량 × 처음·끝 페이드(t) × (1 − (1 − 말할 때 비율) × 말 가림(t))
    말 가림(t): 말 구간 [a, b]마다 a − LEAD부터 a까지 0→1로 올라가고, b부터 b + RELEASE까지 1→0으로 내려간다
               (말이 시작되기 '전에' 미리 줄인다 — 압축기(sidechain)는 말소리가 들린 뒤에야 줄인다)
    말 구간은 결과 영상 기준(결과 초)이고, 사이가 LEAD + RELEASE보다 가까우면 하나로 합친다 (오르내림이 겹치지 않게)
"""

from __future__ import annotations

LEAD = 0.4          # 말 시작 몇 초 전부터 줄이기 시작하나
RELEASE = 0.6       # 말이 끝나고 몇 초 동안 다시 키우나
FADE_IN = 1.5       # 영상 처음
FADE_OUT = 2.5      # 영상 끝


def _clip(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a - out[-1][1] < LEAD + RELEASE:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


def duck_amount(t: float, spans: list[tuple[float, float]]) -> float:
    """0(말 없음) ~ 1(말하는 중). spans는 merge_spans를 거친 것."""
    return min(1.0, sum(_clip((t - (a - LEAD)) / LEAD) * _clip((b + RELEASE - t) / RELEASE) for a, b in spans))


def gain_at(t: float, spans: list[tuple[float, float]], volume: float, duck_level: float, duck: bool,
            duration: float) -> float:
    fade = _clip(t / FADE_IN) * _clip((duration - t) / FADE_OUT)
    ducked = 1 - (1 - duck_level) * duck_amount(t, spans) if duck else 1.0
    return volume * fade * ducked
