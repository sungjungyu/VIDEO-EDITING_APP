"""
미디어 엔진 진입점 — 팀원2(백엔드)가 호출하는 유일한 공개 API.

사용 예시 (팀원2 담당):
    from starlette.concurrency import run_in_threadpool
    output = await run_in_threadpool(render_video, source_path, edit_data, callback)
"""
from typing import Callable

from . import cutter, ass_generator, timestamp_mapper
from .utils.ffmpeg_wrapper import run_ffmpeg, get_duration
from .utils.file_utils import make_temp_path, make_output_path, remove_files
from .exceptions import FFmpegEncodingError, MediaEngineError
from . import config


def render_video(
    source_path: str,
    edit_data: dict,
    progress_callback: Callable[[str, int], None],
) -> str:
    """
    edit_data = {
        "cuts": [{"start": float, "end": float}, ...],
        "subtitles": [
            {
                "start": float,
                "end": float,
                "text": str,
                "words": [{"word": str, "start": float, "end": float}, ...]  # 카라오케용, 선택
            }
        ],
        "style_preset": "매운맛" | "순한맛" | "정석맛"
    }

    progress_callback(stage, percent) → None
      stage: "cutting" | "generating_subtitles" | "encoding" | "done"

    반환값: 최종 렌더링된 영상의 절대경로 (str)
    실패 시: MediaEngineError 계열 예외
    """
    cuts: list[dict] = edit_data["cuts"]
    subtitles: list[dict] = edit_data.get("subtitles", [])
    style_preset: str = edit_data.get("style_preset", "정석맛")

    cut_path: str | None = None
    ass_path: str | None = None

    try:
        # Step 0: 입력 검증
        duration = get_duration(source_path)
        cutter.validate_cuts(cuts, duration)

        # Step 1: 컷 편집
        progress_callback("cutting", 5)
        cut_path = cutter.cut(source_path, cuts)

        # Step 2: 자막 타임스탬프 재계산
        remapped_subs = timestamp_mapper.remap(cuts, subtitles)

        # Step 3: .ass 자막 파일 생성
        progress_callback("generating_subtitles", 15)
        ass_path = make_temp_path(".ass")
        ass_generator.generate(remapped_subs, style_preset, ass_path)

        # Step 4: 자막 합성 → 최종 인코딩
        progress_callback("encoding", 20)
        output_path = make_output_path(".mp4")
        _encode_with_subtitles(cut_path, ass_path, output_path)

        progress_callback("done", 100)
        return output_path

    finally:
        # Step 5: 임시파일 정리
        remove_files(cut_path, ass_path)


def _encode_with_subtitles(cut_path: str, ass_path: str, output_path: str) -> None:
    # Windows 경로의 역슬래시와 콜론을 FFmpeg subtitles 필터용으로 이스케이프
    ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")

    code, stderr = run_ffmpeg([
        "-i", cut_path,
        "-vf", f"subtitles='{ass_escaped}'",
        "-c:v", config.VIDEO_CODEC,
        "-crf", str(config.CRF),
        "-preset", config.PRESET,
        "-c:a", config.AUDIO_CODEC,
        output_path,
    ])

    if code != 0:
        raise FFmpegEncodingError(
            f"최종 인코딩 실패.\nFFmpeg stderr:\n{stderr}"
        )
