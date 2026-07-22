"""
미디어 엔진 독립 동작 테스트
- FFmpeg로 테스트용 영상 자동 생성 (외부 파일 불필요)
- render_video() 5단계 파이프라인 전체 검증
"""
import os
import sys
import subprocess
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from media_engine import render_video
from media_engine.exceptions import MediaEngineError
from media_engine import config as me_config


def make_test_video(output_path: str, duration: int = 20) -> None:
    """FFmpeg로 색상 테스트 영상을 생성한다."""
    print(f"  테스트 영상 생성 중... ({duration}초)")
    cmd = [
        me_config.FFMPEG_BIN, "-y",
        "-f", "lavfi",
        "-i", f"color=c=blue:size=1280x720:rate=30:duration={duration}",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-crf", "28", "-preset", "fast",
        "-c:a", "aac",
        output_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print("테스트 영상 생성 실패:", result.stderr.decode(errors="replace"))
        sys.exit(1)
    print(f"  테스트 영상 생성 완료: {output_path}")


def progress(stage: str, pct: int) -> None:
    bar = "#" * (pct // 5) + "." * (20 - pct // 5)
    print(f"  [{bar}] {pct:3d}%  {stage}")


def run_test(label: str, edit_data: dict, video_path: str) -> bool:
    print(f"\n{'='*55}")
    print(f"  테스트: {label}")
    print(f"{'='*55}")
    try:
        output = render_video(video_path, edit_data, progress)
        size_kb = os.path.getsize(output) // 1024
        print(f"\n  결과 파일: {output}")
        print(f"  파일 크기: {size_kb} KB")
        print(f"  [PASS] {label}")
        return True
    except MediaEngineError as e:
        print(f"\n  [FAIL] {type(e).__name__}: {e}")
        return False
    except Exception as e:
        print(f"\n  [ERROR] 예상치 못한 예외: {type(e).__name__}: {e}")
        return False


def main():
    print("\n" + "="*55)
    print("  미디어 엔진 동작 테스트")
    print("="*55)

    video_path = os.path.join(tempfile.gettempdir(), "me_test_source.mp4")
    make_test_video(video_path, duration=20)

    results = []

    # 테스트 1: 기본 컷 편집 (자막 없음)
    results.append(run_test(
        "기본 컷 편집 (자막 없음)",
        {
            "cuts": [{"start": 0.0, "end": 5.0}, {"start": 10.0, "end": 15.0}],
            "subtitles": [],
            "style_preset": "정석맛",
        },
        video_path,
    ))

    # 테스트 2: 자막 포함 (정석맛)
    results.append(run_test(
        "자막 포함 -정석맛",
        {
            "cuts": [{"start": 0.0, "end": 8.0}],
            "subtitles": [
                {"start": 0.5, "end": 3.0, "text": "안녕하세요"},
                {"start": 3.5, "end": 7.0, "text": "미디어 엔진 테스트입니다"},
            ],
            "style_preset": "정석맛",
        },
        video_path,
    ))

    # 테스트 3: 카라오케 하이라이트 (매운맛)
    results.append(run_test(
        "카라오케 하이라이트 -매운맛",
        {
            "cuts": [{"start": 2.0, "end": 12.0}],
            "subtitles": [
                {
                    "start": 2.5,
                    "end": 6.0,
                    "text": "카라오케 자막 테스트",
                    "words": [
                        {"word": "카라오케", "start": 2.5, "end": 3.5},
                        {"word": "자막", "start": 3.7, "end": 4.5},
                        {"word": "테스트", "start": 4.7, "end": 5.8},
                    ],
                }
            ],
            "style_preset": "매운맛",
        },
        video_path,
    ))

    # 테스트 4: 순한맛
    results.append(run_test(
        "자막 포함 -순한맛",
        {
            "cuts": [{"start": 0.0, "end": 6.0}, {"start": 14.0, "end": 18.0}],
            "subtitles": [
                {"start": 1.0, "end": 4.0, "text": "순한맛 스타일 테스트"},
            ],
            "style_preset": "순한맛",
        },
        video_path,
    ))

    # 테스트 5: 유효성 검사 -잘못된 cuts (실패해야 정상)
    results.append(run_test(
        "유효성 검사 -겹치는 cuts (실패 예상)",
        {
            "cuts": [{"start": 0.0, "end": 10.0}, {"start": 5.0, "end": 15.0}],
            "subtitles": [],
            "style_preset": "정석맛",
        },
        video_path,
    ))
    # 테스트 5는 InvalidCutRangeError가 나야 정상이므로 결과 반전
    results[-1] = not results[-1]

    # 결과 요약
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*55}")
    print(f"  결과: {passed}/{total} 통과")
    print("="*55 + "\n")

    # 임시 영상 정리
    try:
        os.remove(video_path)
    except OSError:
        pass

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
