"""화면 품질 곡선 테스트: 선명도·노출·손떨림(위상 상관)과 B롤 구간 고르기."""

from __future__ import annotations

import numpy as np

from tests.fixtures.media import make_clip
from vibecut.analysis import quality as q

RNG = np.random.default_rng(0)
TEXTURE = (RNG.random((200, 200)) * 255).astype(np.float32)


def _blur(img: np.ndarray, times: int = 4) -> np.ndarray:
    for _ in range(times):
        img = (img + np.roll(img, 1, 0) + np.roll(img, -1, 0) + np.roll(img, 1, 1) + np.roll(img, -1, 1)) / 5
    return img


def crops(offsets: list[tuple[int, int]], src: np.ndarray = TEXTURE) -> np.ndarray:
    """큰 무늬에서 (y, x) 위치를 옮겨 가며 자른 128×128 프레임 = 카메라가 움직인 화면."""
    return np.stack([src[16 + y:16 + y + 128, 16 + x:16 + x + 128] for y, x in offsets]).astype(np.uint8)


def test_sharpness_drops_when_blurred_and_exposure_flags_dark_frames():
    sharp = crops([(0, 0)])
    blurred = crops([(0, 0)], _blur(TEXTURE))
    assert q.sharpness(sharp)[0] > 5 * q.sharpness(blurred)[0]
    dark = np.full((1, 128, 128), 8, np.uint8)
    normal = np.full((1, 128, 128), 120, np.uint8)
    blown = np.full((1, 128, 128), 250, np.uint8)
    assert q.exposure(dark)[0] == 0 and q.exposure(normal)[0] == 1 and q.exposure(blown)[0] == 0


def test_phase_correlation_recovers_camera_shift():
    d = q.shifts(crops([(0, 0), (3, -5)]))
    assert tuple(d[1]) == (-3.0, 5.0)        # 화면 내용이 반대 방향으로 3·5px 움직임


def test_smooth_pan_is_stable_but_hand_shake_is_not():
    pan = crops([(0, i * 2) for i in range(10)])                                     # 일정하게 옆으로
    shake = crops([(0, 0) if i % 2 == 0 else (5, -6) for i in range(10)])            # 왔다 갔다
    assert q.stability(pan)[2:-1].min() > 0.9
    assert q.stability(shake)[2:-1].max() < 0.1


def test_best_window_picks_the_best_part_inside_the_quiet_region():
    curve = {"fps": 2.0, "q": [0.2] * 10 + [0.9] * 8 + [0.3] * 10}                   # 5~9초가 좋음
    s, e, mean = q.best_window(curve, 0.0, 14.0)
    assert (s, e) == (5.0, 9.0) and mean > 0.85                                       # 끝의 흐린 1초는 잘라 냄
    assert q.best_window(None, 0.0, 14.0) == (0.2, 5.2, None)                         # 곡선이 없으면 앞쪽
    s, e, mean = q.best_window(curve, 10.0, 11.5)                                      # 2초도 안 되는 구간
    assert mean is None and e - s < 2.0


def test_quality_curve_of_real_clip_is_cached(tmp_path):
    video = make_clip(tmp_path / "a.mp4", 4.0, luma=False, audio=False)
    curve = q.clip_quality(video, "abc", tmp_path / "cache")
    assert len(curve["q"]) == 8 and all(0.0 <= v <= 1.0 for v in curve["q"])
    assert list((tmp_path / "cache").glob("abc_quality_v1_*.json"))
    assert q.clip_quality(tmp_path / "없는파일.mp4", "abc", tmp_path / "cache") == curve   # 두 번째는 캐시
