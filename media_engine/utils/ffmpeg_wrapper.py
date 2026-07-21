import subprocess
import re
from .. import config


def run_ffmpeg(args: list[str], timeout: int = 600) -> tuple[int, str]:
    """
    FFmpeg를 실행하고 (returncode, stderr) 를 반환한다.
    stdout은 /dev/null로 버린다.
    """
    cmd = [config.FFMPEG_BIN, "-y"] + args
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return result.returncode, result.stderr


def run_ffprobe(args: list[str]) -> tuple[int, str, str]:
    """
    FFprobe를 실행하고 (returncode, stdout, stderr) 를 반환한다.
    """
    cmd = [config.FFPROBE_BIN] + args
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout, result.stderr


def get_duration(video_path: str) -> float:
    """영상 길이(초)를 반환한다."""
    code, stdout, _ = run_ffprobe([
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ])
    if code != 0:
        raise RuntimeError(f"ffprobe 실패: {video_path}")
    return float(stdout.strip())


def parse_time_from_stderr(stderr: str) -> float | None:
    """
    FFmpeg stderr에서 'time=HH:MM:SS.ss' 패턴을 파싱해 초로 반환한다.
    진행률 계산용 (확장 목표).
    """
    matches = re.findall(r"time=(\d+):(\d+):([\d.]+)", stderr)
    if not matches:
        return None
    h, m, s = matches[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)
