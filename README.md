# SRT Video Generator

Create a timestamp-synchronized slideshow video from a folder of images, an SRT subtitle file, and optional audio. The browser interface lets you choose landscape or portrait output, animated zoom, and image-change sound effects, then preview and download the result.

> This repository is named **Stick-man-Video-Maker** on GitHub; the application itself is called **SRT Video Generator**.

## Features

- Match images to SRT cue start times; images are naturally sorted by filename.
- Render 16:9 landscape (1920 × 1080) or 9:16 portrait (1080 × 1920) MP4 video.
- Optionally animate a subtle zoom and mix image-change sounds with music or narration.
- Show render progress and allow an active render to be canceled.
- Preview the finished video in the browser and download it.
- Run locally on Windows or deploy the frontend and backend separately.

## Run locally on Windows

### Portable setup

1. Install a Windows FFmpeg build and place its executable at `ffmpeg\ffmpeg.exe`.
2. Run `setup_portable_python.bat` once to download the portable Python runtime and install the app's Python packages.
3. Run `SRT_Video_Generator.bat` to start the app and open `http://127.0.0.1:8765`.

The portable Python runtime, FFmpeg executable, generated videos, and server log are local files and are intentionally excluded from Git.

### Use an existing Python installation

Install Python 3.10 or later and FFmpeg. Make sure `ffmpeg` is on `PATH`, or set `FFMPEG_PATH` to the executable. From PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765` in a browser. To allow a separately hosted frontend to call this backend, set `CORS_ORIGINS` to its exact origin before starting Uvicorn, for example:

```powershell
$env:CORS_ORIGINS = "https://your-site.netlify.app"
```

## Deploy the frontend to Netlify

Netlify can serve the static frontend, but it cannot run this app's long-running Python/FFmpeg video-rendering jobs. A separate backend is required for video generation.

1. Import this GitHub repository into Netlify.
2. Use `web` as the publish directory. No build command is needed; `netlify.toml` configures the publish directory and response headers.
3. After deploying the backend, edit `web/config.js` and set `window.APP_API_BASE_URL` to its public HTTPS origin:

   ```js
   window.APP_API_BASE_URL = 'https://your-api.example.com';
   ```

4. Set the backend's `CORS_ORIGINS` to the exact HTTPS origin of your Netlify site, then redeploy the frontend.

Keep the API URL free of a trailing slash. The default empty value keeps the frontend working with the locally hosted app.

## Backend hosting and Docker

The backend needs Python, FFmpeg, writable temporary/output storage, and a process that can stay alive while a render runs. A small Linux VM is a better fit than a serverless function for this workload.

For a $0 target, Oracle Cloud Infrastructure's Always Free Ampere VM is one possible option. Free resource availability and eligibility can vary; account verification may require a payment card, and you are responsible for VM maintenance, firewall rules, HTTPS, and avoiding paid resources. Review the provider's [current Free Tier terms](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm) before signing up. Free-tier service availability and limits can change.

The included `Dockerfile` installs Linux FFmpeg and runs the FastAPI app on port 7860. It does not package the Windows FFmpeg executable. Build and run the image on the VM:

```sh
docker build -t srt-video-generator .
docker run -d --name srt-video-generator --restart unless-stopped \
  -p 127.0.0.1:8000:7860 \
  -e CORS_ORIGINS=https://your-site.netlify.app \
  -v srt-video-output:/app/output \
  srt-video-generator
```

The container is bound to the VM's loopback interface in this example. Put a TLS reverse proxy such as Caddy in front of it and expose only HTTPS publicly. Configure DNS and the VM firewall for your chosen proxy and domain; do not expose the backend over plain HTTP to the public internet.

The named Docker volume preserves completed videos across container restarts. Active jobs and job status are held in memory, so a backend restart interrupts active renders. The app is designed for personal/small-scale use, not unrestricted public rendering.

## Files and configuration

| Path | Purpose |
| --- | --- |
| `server.py` | FastAPI endpoints, upload handling, job status, and static-file serving |
| `video_generator.py` | FFmpeg slideshow and audio rendering |
| `srt_parser.py` | SRT cue-time parsing and validation |
| `web/` | Static browser interface |
| `web/config.js` | Frontend API base URL |
| `netlify.toml` | Netlify publish directory and response headers |
| `Dockerfile` | Linux backend image with FFmpeg |
| `requirements.txt` | Python dependencies |

`FFMPEG_PATH` can explicitly select an FFmpeg executable. Otherwise the server checks for a bundled executable (`ffmpeg\ffmpeg.exe` on Windows or `ffmpeg/ffmpeg` on Linux), then searches `PATH`. `CORS_ORIGINS` is a comma-separated list of allowed frontend origins; locally it defaults to `http://localhost:8765` and `http://127.0.0.1:8765`.

## Storage and privacy

Uploaded images, audio, and SRT files are sent to the backend for rendering. Temporary inputs are removed when rendering finishes. Completed videos are written to `output/`; starting a new generation removes previous MP4 files. There is no user account system or multi-user isolation, so do not expose a shared instance for public uploads without adding appropriate access controls, upload limits, and storage policies.

## License

No license is currently specified. Add a license before allowing others to redistribute or reuse the project.
