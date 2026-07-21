"""
FFmpeg 컷 편집 모듈

Step 1: concat demuxer + -c copy 무손실 시도
         실패 시(키프레임 불일치 등): 전체 재인코딩으로 fallback
"""
import os
from .utils.ffmpeg_wrapper import run_ffmpeg
from .utils.file_utils import make_temp_path, remove_files
from .exceptions import InvalidCutRangeError, FFmpegCuttingError
from . import config


def validate_cuts(cuts: list[dict], duration: float) -> None:
    """cuts 구간의 유효성을 검사한다. 실패 시 InvalidCutRangeError."""
    if not cuts:
        raise InvalidCutRangeError("cuts가 비어있습니다.")

    sorted_cuts = sorted(cuts, key=lambda c: c["start"])
    for i, cut in enumerate(sorted_cuts):
        s, e = cut["start"], cut["end"]
        if s < 0 or e < 0:
            raise InvalidCutRangeError(f"cuts[{i}]: 음수 타임스탬프 ({s}, {e})")
        if s >= e:
            raise InvalidCutRangeError(f"cuts[{i}]: start({s}) >= end({e})")
        if e > duration + 0.1:
            raise InvalidCutRangeError(
                f"cuts[{i}]: end({e})가 영상 길이({duration:.3f}s)를 초과합니다."
            )
        if i > 0:
            prev_end = sorted_cuts[i - 1]["end"]
            if s < prev_end:
                raise InvalidCutRangeError(
                    f"cuts[{i}]: start({s})가 이전 구간 end({prev_end})보다 앞입니다 (겹침)."
                )


def cut(source_path: str, cuts: list[dict]) -> str:
    """
    source_path: 원본 영상 절대경로
    cuts: 유지할 구간 목록 (validate_cuts 통과 후 호출)

    반환: cut_only.mp4 절대경로 (임시파일)
    실패 시: FFmpegCuttingError
    """
    output_path = make_temp_path("_cut.mp4")

    # concat list 파일 작성
    list_path = make_temp_path(".txt")
    try:
        _write_concat_list(source_path, cuts, list_path)

        # 1차 시도: 무손실 스트림 복사
        code, stderr = run_ffmpeg([
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output_path,
        ])
        if code == 0 and os.path.exists(output_path):
            return output_path

        # fallback: 전체 재인코딩
        remove_files(output_path)
        code, stderr = run_ffmpeg([
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c:v", config.VIDEO_CODEC,
            "-crf", str(config.CRF),
            "-preset", config.PRESET,
            "-c:a", config.AUDIO_CODEC,
            output_path,
        ])
        if code != 0 or not os.path.exists(output_path):
            raise FFmpegCuttingError(
                f"컷 편집 실패 (-c copy 및 재인코딩 fallback 모두 실패).\nFFmpeg stderr:\n{stderr}"
            )
        return output_path

    finally:
        remove_files(list_path)


def _write_concat_list(source_path: str, cuts: list[dict], list_path: str) -> None:
    """concat demuxer 용 텍스트 파일을 작성한다."""
    lines = []
    for cut in sorted(cuts, key=lambda c: c["start"]):
        escaped = source_path.replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
        lines.append(f"inpoint {cut['start']:.6f}")
        lines.append(f"outpoint {cut['end']:.6f}")
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
