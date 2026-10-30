import subprocess
import threading
from pathlib import Path

from srt_parser import Cue

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_FPS = 30
MAX_ZOOM = 1.05
MAX_ZOOM_DURATION_SECONDS = 1.0
MOTION_WIDTH = 2560
MOTION_HEIGHT = 1440
OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
ASPECT_RATIOS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
}


class GenerationCanceled(Exception):
    pass


def _duration_seconds(cues: list[Cue], index: int) -> float:
    if index + 1 < len(cues):
        duration_ms = cues[index + 1].start_ms - cues[index].start_ms
    else:
        duration_ms = max(cues[index].end_ms - cues[index].start_ms, 1_000)
    return max(duration_ms / 1_000, 0.1)


def create_video(
    images: list[Path],
    cues: list[Cue],
    ffmpeg_path: Path,
    work_dir: Path,
    output_path: Path,
    on_image_started=None,
    cancel_event: threading.Event | None = None,
    audio_path: Path | None = None,
    apply_zoom: bool = True,
    sfx_path: Path | None = None,
    aspect_ratio: str = "16:9",
    on_stage_changed=None,
) -> None:
    if len(images) < len(cues):
        raise ValueError(
            f"The SRT contains {len(cues)} cues, but only {len(images)} images were provided."
        )
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError("Aspect ratio must be 16:9 or 9:16.")

    output_width, output_height = ASPECT_RATIOS[aspect_ratio]
    motion_width = output_width * 2
    motion_height = output_height * 2

    segments_dir = work_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    segment_paths = []

    for index, cue in enumerate(cues):
        if on_image_started:
            on_image_started(index, images[index].name)
        segment_path = segments_dir / f"segment_{index:05d}.mp4"
        duration = _duration_seconds(cues, index)
        frame_count = max(round(duration * VIDEO_FPS), 3)
        if apply_zoom:
            zoom_frame_count = max(
                min(frame_count, round(MAX_ZOOM_DURATION_SECONDS * VIDEO_FPS)),
                3,
            )
            zoom_span = max(zoom_frame_count - 1, 1)
            zoom_frame = f"min(on\\,{zoom_span})"
            eased_progress = f"(1-cos(PI*{zoom_frame}/{zoom_span}))/2"
            if index % 2 == 0:
                zoom_expression = f"1+{MAX_ZOOM - 1:.4f}*{eased_progress}"
            else:
                zoom_expression = f"{MAX_ZOOM:.4f}-{MAX_ZOOM - 1:.4f}*{eased_progress}"
            video_filter = (
                f"scale={motion_width}:{motion_height}:force_original_aspect_ratio=increase,"
                f"crop={motion_width}:{motion_height},"
                f"zoompan=z='{zoom_expression}':x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':d={frame_count}:s={motion_width}x{motion_height}:fps={VIDEO_FPS},"
                f"scale={output_width}:{output_height},"
                "format=yuv420p"
            )
        else:
            video_filter = (
                f"scale={output_width}:{output_height}:force_original_aspect_ratio=increase,"
                f"crop={output_width}:{output_height},"
                "format=yuv420p"
            )
        command = [
            str(ffmpeg_path),
            "-y",
            *( ["-loop", "1"] if not apply_zoom else [] ),
            "-i",
            str(images[index]),
            "-vf",
            video_filter,
            *( ["-t", f"{duration:.3f}"] if not apply_zoom else [] ),
            "-frames:v",
            str(frame_count),
            "-an",
            str(segment_path),
        ]
        _run_ffmpeg(command, cancel_event)
        segment_paths.append(segment_path)

    concat_file = work_dir / "concat.txt"
    concat_file.write_text(
        "".join(f"file '{path.as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in segment_paths),
        encoding="utf-8",
    )
    sfx_audio_path = None
    if sfx_path is not None:
        if on_stage_changed:
            on_stage_changed("Preparing image-change sounds...", 89)
        sfx_audio_path = work_dir / "image_change_sfx.wav"
        _create_sfx_track(
            ffmpeg_path,
            sfx_path,
            cues,
            sfx_audio_path,
            cancel_event,
        )

    if on_stage_changed:
        on_stage_changed("Combining video segments...", 90)
    final_input_path = output_path if audio_path is None and sfx_audio_path is None else work_dir / "slideshow_silent.mp4"
    _run_ffmpeg(
        [
            str(ffmpeg_path),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(final_input_path),
        ],
        cancel_event,
    )

    if audio_path is not None or sfx_audio_path is not None:
        if on_stage_changed:
            on_stage_changed("Adding audio track...", 96)
        mux_command = [str(ffmpeg_path), "-y", "-i", str(final_input_path)]
        if audio_path is not None:
            mux_command.extend(["-stream_loop", "-1", "-i", str(audio_path)])
        if sfx_audio_path is not None:
            mux_command.extend(["-i", str(sfx_audio_path)])
        if audio_path is not None and sfx_audio_path is not None:
            mux_command.extend([
                "-filter_complex",
                "[1:a]aresample=48000[music];[music][2:a]amix=inputs=2:duration=first:dropout_transition=0[aout]",
                "-map",
                "0:v:0",
                "-map",
                "[aout]",
            ])
        else:
            audio_input_index = 1
            mux_command.extend(["-map", "0:v:0", "-map", f"{audio_input_index}:a:0"])
        mux_command.extend([
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ])
        _run_ffmpeg(mux_command, cancel_event)


def _create_sfx_track(
    ffmpeg_path: Path,
    sfx_path: Path,
    cues: list[Cue],
    output_path: Path,
    cancel_event: threading.Event | None = None,
) -> None:
    delays = []
    elapsed_ms = 0
    for index, cue in enumerate(cues):
        delays.append(elapsed_ms)
        elapsed_ms += round(_duration_seconds(cues, index) * 1_000)

    split_labels = "".join(f"[click{index}]" for index in range(len(delays)))
    delayed_labels = []
    filter_parts = [f"[0:a]asplit={len(delays)}{split_labels};"]
    for index, delay in enumerate(delays):
        label = f"[delayed{index}]"
        delayed_labels.append(label)
        filter_parts.append(f"[click{index}]adelay={delay}|{delay}{label};")
    filter_parts.append(
        f"{''.join(delayed_labels)}amix=inputs={len(delays)}:duration=longest:dropout_transition=0:normalize=0[aout]"
    )
    total_duration = sum(_duration_seconds(cues, index) for index in range(len(cues)))
    _run_ffmpeg(
        [
            str(ffmpeg_path),
            "-y",
            "-i",
            str(sfx_path),
            "-filter_complex",
            "".join(filter_parts),
            "-map",
            "[aout]",
            "-t",
            f"{total_duration:.3f}",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(output_path),
        ],
        cancel_event,
    )

def _run_ffmpeg(command: list[str], cancel_event: threading.Event | None = None) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    while process.poll() is None:
        if cancel_event and cancel_event.is_set():
            process.terminate()
            process.wait()
            raise GenerationCanceled()
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            continue

    if process.returncode != 0:
        raise RuntimeError("FFmpeg could not render this image or combine the video segments.")
