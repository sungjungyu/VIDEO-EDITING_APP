"""렌더: EditPlan → FFmpeg 명령 하나(필터 그래프 파일 + ASS 자막 파일) → 실행(진행률·취소) → 결과 길이 검증.

예전 media_engine은 concat demuxer + `-c copy`로 잘라서 컷이 키프레임에 끌려갔다
(키프레임 5초 간격 영상에서 5초를 남기면 8.09초가 나옴). 여기서는 구간마다 trim/atrim으로
프레임 단위로 자르고, 클립 통일·페이드·줌인·자막까지 한 번에 처리해 인코딩도 한 번만 한다.

    [입력 클립마다 -ss로 앞부분 건너뛰기]
      → 구간마다: trim(반 프레임 앞으로 당겨 경계 프레임이 확실하게) · 화면 채우기(scale+crop) · 펀치인(overlay)
                  atrim · 48kHz 스테레오 · 앞뒤 25ms 페이드 (소리 없는 클립은 무음 생성)
      → concat (구간마다 영상·소리 길이를 맞춰 이어 붙임) → fps 통일 → 자막(libass) → yuv420p
      → 목소리 다듬기(highpass 80Hz + afftdn 잡음 줄이기) → 음량 고르게(loudnorm)
      → 배경음악(있으면): 반복 재생해 길이를 맞추고 음량 고르게 → 크기 규칙(domain/mix.py)을 ffmpeg 식으로 → 섞기
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.mix import FADE_IN, FADE_OUT, LEAD, RELEASE
from ..domain.models import ClipInfo, EditPlan, KeepRange, MusicSpec
from ..media.ffmpeg import HDR_TONEMAP_FILTER, filter_script_args, run_with_progress, supports_tonemap
from ..media.probe import probe
from . import fonts
from .ass import build_ass

log = logging.getLogger("vibecut.render")

SEEK_MIN = 5.0          # 첫 구간이 이보다 뒤에서 시작하면 입력 탐색(-ss)으로 앞부분을 디코딩하지 않는다


@dataclass
class RenderSpec:
    args: list[str]
    filter_script: str
    ass_text: str | None
    width: int
    height: int
    duration: float
    font_files: list[Path] = field(default_factory=list)


def _seconds(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".") if x else "0"


def _input_window(ranges: list[KeepRange], fps: float) -> tuple[float, float]:
    """입력 탐색 시작점(프레임 격자 위)과 읽을 길이."""
    first, last = min(r.start for r in ranges), max(r.end for r in ranges)
    seek = 0.0
    if first - 1.0 >= SEEK_MIN:
        seek = first - 1.0
        if fps > 0:
            seek = int(seek * fps) / fps
    return seek, last - seek + 1.0


def music_gain_expr(music: MusicSpec, spans: list[tuple[float, float]], duration: float) -> str:
    """domain/mix.py gain_at과 같은 식 (ffmpeg volume 필터, t = 결과 초)."""
    fade = f"clip(t/{FADE_IN:g},0,1)*clip(({_seconds(duration)}-t)/{FADE_OUT:g},0,1)"
    expr = f"{music.volume:.4f}*{fade}"
    if music.duck and spans:
        ramps = "+".join(f"clip((t-({_seconds(a - LEAD)}))/{LEAD:g},0,1)"     # 괄호: a − LEAD는 음수일 수 있다
                         f"*clip(({_seconds(b + RELEASE)}-t)/{RELEASE:g},0,1)" for a, b in spans)
        expr += f"*(1-{1 - music.duck_level:.4f}*min(1,{ramps}))"
    return expr


def compile_render(plan: EditPlan, clips: dict[str, ClipInfo], files: dict[str, Path], quality: str,
                   output_name: str, music_file: Path | None = None) -> RenderSpec:
    """quality: preview(짧은 변 540px, 빠른 인코딩) | final(설정 해상도). music_file: 배경음악 (없으면 None)."""
    resolution = 540 if quality == "preview" else plan.output.resolution
    width, height = plan.output.size(resolution)
    out_fps = plan.output.fps
    opts = plan.options
    fade = max(0.0, opts.fade_ms / 1000)

    order: list[str] = []
    for k in plan.keep:
        if k.clip_id not in order:
            order.append(k.clip_id)
    args: list[str] = ["-loglevel", "error"]
    seeks: dict[str, float] = {}
    index: dict[str, int] = {}
    for i, clip_id in enumerate(order):
        clip = clips[clip_id]
        seek, length = _input_window([k for k in plan.keep if k.clip_id == clip_id], clip.fps)
        seeks[clip_id] = seek
        index[clip_id] = i
        if seek > 0:
            args += ["-ss", _seconds(seek)]
        args += ["-t", _seconds(length), "-i", str(files[clip_id])]
    if music_file is not None:
        args += ["-stream_loop", "-1", "-i", str(music_file)]          # 영상보다 짧으면 반복

    graph: list[str] = []
    pairs: list[str] = []
    fit = (f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=bicubic,"
           f"crop={width}:{height},setsar=1")
    for n, k in enumerate(plan.keep):
        clip = clips[k.clip_id]
        j, seek = index[k.clip_id], seeks[k.clip_id]
        s, e = k.start - seek, k.end - seek
        dur = k.end - k.start
        half = 0.5 / clip.fps if clip.fps > 0 else 0.0
        effects = [fx for fx in plan.effects if fx.clip_id == k.clip_id and fx.end > k.start and fx.start < k.end]
        if clip.has_video:
            trim = f"trim=start={_seconds(max(0.0, s - half))}:end={_seconds(e - half)}"
            video = f"[{j}:v]{trim},setpts=PTS-STARTPTS,{fit}"
            if clip.hdr and supports_tonemap():
                video += f",{HDR_TONEMAP_FILTER}"
        else:
            video = f"color=c=black:s={width}x{height}:r={out_fps}:d={_seconds(dur)},setsar=1"
        if effects:
            windows = "+".join(f"between(t,{_seconds(max(fx.start, k.start) - k.start)},"
                               f"{_seconds(min(fx.end, k.end) - k.start)})" for fx in effects)
            scale = max(fx.scale for fx in effects)
            graph.append(f"{video},split=2[vb{n}][vz{n}]")
            graph.append(f"[vz{n}]scale=iw*{scale}:ih*{scale}:flags=bicubic,crop={width}:{height}[vzc{n}]")
            graph.append(f"[vb{n}][vzc{n}]overlay=enable='{windows}'[v{n}]")
        else:
            graph.append(f"{video}[v{n}]")
        if clip.has_audio:
            audio = (f"[{j}:a]atrim=start={_seconds(max(0.0, s))}:end={_seconds(e)},asetpts=PTS-STARTPTS,"
                     f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo")
        else:
            audio = f"anullsrc=r=48000:cl=stereo,atrim=duration={_seconds(dur)}"
        if fade > 0 and dur > 4 * fade:
            audio += f",afade=t=in:st=0:d={_seconds(fade)},afade=t=out:st={_seconds(dur - fade)}:d={_seconds(fade)}"
        graph.append(f"{audio}[a{n}]")
        pairs.append(f"[v{n}][a{n}]")
    graph.append(f"{''.join(pairs)}concat=n={len(plan.keep)}:v=1:a=1[vc][ac]")

    ass_text = build_ass(plan.events, plan.styles, width, height) if plan.events else None
    font_files: list[Path] = []
    post = f"[vc]fps={out_fps}:eof_action=pass"     # 기본(round)은 마지막 프레임을 버려 1프레임 짧아진다
    if ass_text:
        used = {plan.styles[e.style].font if e.style in plan.styles else "Malgun Gothic" for e in plan.events}
        for family in used:
            for bold in (False, True):
                path = fonts.find_font_file(family, bold)
                if path and path not in font_files:
                    font_files.append(path)
        post += ",subtitles=filename=subs.ass" + (":fontsdir=fonts" if font_files else "")
    graph.append(f"{post},format=yuv420p[vout]")
    # 소리 끝을 계획 길이에 맞춘다 (loudnorm은 마지막 패킷을 길게 기록해 결과 길이가 40ms쯤 늘어난다)
    end = f"atrim=duration={_seconds(plan.duration)}"
    voice = "highpass=f=80,afftdn=nr=12:nf=-40," if opts.voice_clean else ""
    level = "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000," if opts.loudness else ""
    if music_file is None:
        graph.append(f"[ac]{voice}{level}{end}[aout]")
    else:
        graph.append(f"[ac]{voice}{level}{end}[sp]")
        gain = music_gain_expr(plan.music, plan.speech, plan.duration)
        graph.append(f"[{len(order)}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,{end},"
                     f"asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,"
                     f"volume=eval=frame:volume='{gain}'[bgm]")
        graph.append(f"[sp][bgm]amix=inputs=2:duration=first:normalize=0,{end}[aout]")

    if quality == "preview":
        encode = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-c:a", "aac", "-b:a", "128k"]
    else:
        encode = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k"]
    args += [*filter_script_args("graph.txt"), "-map", "[vout]", "-map", "[aout]", *encode,
             "-ar", "48000", "-movflags", "+faststart", output_name]
    return RenderSpec(args=args, filter_script=";\n".join(graph), ass_text=ass_text, width=width, height=height,
                      duration=plan.duration, font_files=font_files)


def prepare_workdir(spec: RenderSpec, workdir: Path) -> None:
    """필터 그래프·자막·글꼴을 작업 폴더에 둔다. ffmpeg는 이 폴더에서 실행해 상대 경로로 읽는다
    (윈도우 경로의 C: 같은 콜론을 필터 문법에서 이스케이프할 필요가 없다)."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "graph.txt").write_text(spec.filter_script, encoding="utf-8")
    if spec.ass_text:
        (workdir / "subs.ass").write_text(spec.ass_text, encoding="utf-8-sig")
    if spec.font_files:
        font_dir = workdir / "fonts"
        font_dir.mkdir(exist_ok=True)
        for path in spec.font_files:
            target = font_dir / path.name
            if not target.exists():
                shutil.copyfile(path, target)


# ---------------------------------------------------------------- 실행

def render_plan(plan: EditPlan, clips: dict[str, ClipInfo], files: dict[str, Path], quality: str, output: Path,
                workdir: Path, on_progress: Callable[[float], None] | None = None,
                cancel: threading.Event | None = None, keep_workdir: bool = False,
                music_file: Path | None = None) -> dict:
    """결과 파일을 output에 만들고 측정값을 돌려준다.
    duration은 실제 결과 길이, error_ms는 계획 길이와의 차이 (1프레임 = 33ms 안쪽이어야 정상)."""
    if not plan.keep:
        raise ValueError("남길 구간이 없어 렌더할 수 없습니다.")
    started = time.time()
    output.parent.mkdir(parents=True, exist_ok=True)
    spec = compile_render(plan, clips, files, quality, "out.mp4", music_file)
    prepare_workdir(spec, workdir)
    log.info("렌더 시작: %s, 구간 %d개, 예상 %.1f초, %dx%d", quality, len(plan.keep), spec.duration,
             spec.width, spec.height)
    try:
        run_with_progress(spec.args, spec.duration, on_progress, cancel, cwd=workdir)
        result = workdir / "out.mp4"
        info = probe(result)
        shutil.move(str(result), str(output))
    finally:
        if not keep_workdir:
            shutil.rmtree(workdir, ignore_errors=True)
    error_ms = round((info.duration - spec.duration) * 1000, 1)
    elapsed = round(time.time() - started, 2)
    log.info("렌더 완료: %.2f초 (계획과 차이 %+.0fms), %.1f초 걸림", info.duration, error_ms, elapsed)
    return {
        "width": spec.width, "height": spec.height, "duration": info.duration, "plan_duration": spec.duration,
        "error_ms": error_ms, "elapsed_sec": elapsed, "size_bytes": output.stat().st_size,
    }
