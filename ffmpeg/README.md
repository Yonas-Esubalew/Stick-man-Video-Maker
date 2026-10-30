Place the native FFmpeg executable for packaged builds in this folder:

- Windows: `ffmpeg.exe`
- macOS/Linux: `ffmpeg`

The Electron main process resolves this folder through `process.resourcesPath` and never requires a global FFmpeg installation. Choose and distribute an FFmpeg build whose license terms fit the application before shipping.
