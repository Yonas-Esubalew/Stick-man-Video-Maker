import os
import shutil
import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app_config import APP_DESCRIPTION, APP_NAME, APP_VERSION
from srt_parser import parse_srt
from video_generator import GenerationCanceled, SUPPORTED_IMAGE_EXTENSIONS, create_video

ROOT_DIR = Path(__file__).resolve().parent
bundled_ffmpeg_path = ROOT_DIR / "ffmpeg" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
FFMPEG_PATH = Path(
    os.environ.get("FFMPEG_PATH")
    or (bundled_ffmpeg_path if bundled_ffmpeg_path.is_file() else shutil.which("ffmpeg"))
    or bundled_ffmpeg_path
)
SFX_PATH = ROOT_DIR / "sfx" / "click.wav"
OUTPUT_DIR = ROOT_DIR / "output"
WEB_DIR = ROOT_DIR / "web"

app = FastAPI(title="SRT Slideshow Generator")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
allowed_origins = [
    origin.strip().rstrip("/")
    for origin in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:8765,http://127.0.0.1:8765",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-App-Version"] = APP_VERSION
        return response


app.add_middleware(NoCacheMiddleware)
JOBS = {}
JOB_CANCEL_EVENTS = {}
JOBS_LOCK = threading.Lock()
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=1)
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def natural_image_order(image: UploadFile):
    filename = Path(image.filename or "").as_posix()
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", filename)]


def _update_job(job_id: str, **updates) -> None:
    with JOBS_LOCK:
        JOBS[job_id].update(updates)


def _remove_previous_videos() -> None:
    for video_path in OUTPUT_DIR.glob("*.mp4"):
        try:
            video_path.unlink()
        except OSError as error:
            raise RuntimeError(f"Could not remove previous video: {video_path.name}") from error


def _safe_video_stem(filename: str) -> str:
    stem = Path(filename).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" .")
    return safe_stem or "generated_video"


def _run_generation(job_id, image_paths, cues, work_dir, output_path, cancel_event, audio_path, apply_zoom, apply_sfx, aspect_ratio):
    total_images = len(cues)

    def image_started(index, filename):
        _update_job(
            job_id,
            current_image=index + 1,
            current_filename=filename,
            progress=round((index / total_images) * 90),
            phase=f"Rendering image {index + 1} of {total_images}",
        )

    def stage_changed(message, progress):
        _update_job(job_id, current_filename="", phase=message, progress=progress)

    try:
        create_video(
            image_paths,
            cues,
            FFMPEG_PATH,
            work_dir,
            output_path,
            on_image_started=image_started,
            cancel_event=cancel_event,
            audio_path=audio_path,
            apply_zoom=apply_zoom,
            sfx_path=SFX_PATH if apply_sfx else None,
            aspect_ratio=aspect_ratio,
            on_stage_changed=stage_changed,
        )
        _update_job(
            job_id,
            state="complete",
            progress=100,
            current_image=total_images,
            current_filename="",
            phase="Complete",
            output_name=output_path.name,
        )
    except GenerationCanceled:
        _update_job(job_id, state="canceled", current_filename="", phase="Canceled", error="Generation canceled.")
    except (ValueError, RuntimeError) as error:
        _update_job(job_id, state="error", error=str(error))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        with JOBS_LOCK:
            JOB_CANCEL_EVENTS.pop(job_id, None)


@app.post("/api/generate")
async def generate_video(
    srt_file: UploadFile = File(...),
    images: list[UploadFile] = File(...),
    audio_file: UploadFile | None = File(None),
    apply_zoom: bool = Form(True),
    apply_sfx: bool = Form(True),
    aspect_ratio: str = Form("16:9"),
):
    if not srt_file.filename or not srt_file.filename.lower().endswith(".srt"):
        raise HTTPException(status_code=400, detail="Please select an SRT file.")
    if not FFMPEG_PATH.is_file():
        raise HTTPException(status_code=500, detail=f"FFmpeg executable not found: {FFMPEG_PATH}")
    if apply_sfx and not SFX_PATH.is_file():
        raise HTTPException(status_code=500, detail=f"Missing bundled click sound: {SFX_PATH}")
    if aspect_ratio not in {"16:9", "9:16"}:
        raise HTTPException(status_code=400, detail="Aspect ratio must be 16:9 or 9:16.")

    valid_images = [
        image for image in images
        if image.filename and Path(image.filename).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    ]
    valid_images.sort(key=natural_image_order)
    if not valid_images:
        raise HTTPException(status_code=400, detail="No supported images were selected.")

    work_dir = Path(tempfile.mkdtemp(prefix="srt_slideshow_"))
    srt_path = work_dir / "captions.srt"
    srt_path.write_bytes(await srt_file.read())

    image_paths = []
    for index, image in enumerate(valid_images):
        image_path = work_dir / f"image_{index:05d}{Path(image.filename).suffix.lower()}"
        image_path.write_bytes(await image.read())
        image_paths.append(image_path)

    audio_path = None
    if audio_file and audio_file.filename:
        audio_extension = Path(audio_file.filename).suffix.lower()
        if audio_extension not in SUPPORTED_AUDIO_EXTENSIONS:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="Unsupported audio format.")
        audio_path = work_dir / f"audio{audio_extension}"
        audio_path.write_bytes(await audio_file.read())

    try:
        cues = parse_srt(srt_path)
    except ValueError as error:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(error)) from error

    if len(image_paths) < len(cues):
        cues = cues[:len(image_paths)]

    try:
        _remove_previous_videos()
    except RuntimeError as error:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(error)) from error

    job_id = uuid4().hex
    output_path = OUTPUT_DIR / f"{_safe_video_stem(srt_file.filename)}.mp4"
    with JOBS_LOCK:
        JOBS[job_id] = {
            "state": "working",
            "progress": 0,
            "current_image": 0,
            "total_images": len(cues),
            "current_filename": "",
            "phase": "Preparing...",
            "error": "",
        }
        JOB_CANCEL_EVENTS[job_id] = threading.Event()
    JOB_EXECUTOR.submit(
        _run_generation,
        job_id,
        image_paths,
        cues,
        work_dir,
        output_path,
        JOB_CANCEL_EVENTS[job_id],
        audio_path,
        apply_zoom,
        apply_sfx,
        aspect_ratio,
    )

    return {"job_id": job_id}


@app.get("/api/version")
async def get_version():
    return {"name": APP_NAME, "description": APP_DESCRIPTION, "version": APP_VERSION}


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Generation job not found.")
        return dict(job)


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        cancel_event = JOB_CANCEL_EVENTS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Generation job not found.")
        if not cancel_event:
            if job["state"] == "working":
                job.update(state="error", phase="Failed", error="The generation worker stopped unexpectedly.")
            return dict(job)
        if job["state"] != "working":
            return dict(job)
        job["state"] = "canceling"
        cancel_event.set()
        return dict(job)


@app.get("/api/jobs/{job_id}/download")
async def download_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Generation job not found.")
        if job["state"] != "complete":
            raise HTTPException(status_code=409, detail="Video generation is not complete.")
        output_name = job["output_name"]

    output_path = OUTPUT_DIR / output_name
    return FileResponse(output_path, media_type="video/mp4", filename=output_name)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
