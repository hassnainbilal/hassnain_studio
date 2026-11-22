# HASSNAIN STUDIO

**An AI-Powered Image & Video Editing Studio.** A local-first Windows-friendly media studio built on React/Vite, FastAPI, Pillow, OpenCV and FFmpeg. Existing editing tools, projects, exports and local storage are retained.

## Requirements
- Windows 10/11 (also works on Linux/macOS with equivalent commands)
- Python 3.10+, Node.js 18+, FFmpeg + ffprobe on PATH
- Internet for first-time Python/model installation; processing runs locally afterward

## Install on Windows
1. Install Python (enable **Add Python to PATH**), Node.js LTS and FFmpeg (`winget install Gyan.FFmpeg`).
2. Extract the project folder.
3. Double-click `install.bat` and wait for dependencies to install.
4. Double-click `start.bat`; open `http://localhost:5173`.

## Manual start commands
Backend (from project root):
```powershell
cd backend
.venv\Scripts\Activate.ps1
python -m uvicorn main:app --reload --port 8000
```
Frontend (second terminal, from project root):
```powershell
cd frontend
npm install
npm run dev
```

## Features
- **Image Editor:** non-destructive controls for brightness, contrast, saturation, sharpness, blur, denoise, crop, rotate, flip, filters and PNG/JPG/WEBP export.
- **Background Remover:** actual `rembg` inference using ONNX Runtime; outputs transparent PNG. First use downloads the model.
- **Image Analysis:** brightness/exposure, contrast, sharpness/blur, noise, saturation, mean RGB/white balance and resolution diagnostics; conservative condition-based auto enhancement.
- **Video Analysis:** FFprobe metadata plus sampled OpenCV brightness, contrast, sharpness, scene-change estimates, aspect ratio and template recommendation.
- **Video Editor / Auto Edit:** silence detection, selectable cuts, color/sharpness cleanup, audio denoise and optional captions.
- **Video Enhancement:** FFmpeg filters for exposure, contrast, saturation, sharpening, denoise, stabilization, resizing, FPS and optional music mix.
- **Auto Captions:** Faster-Whisper transcription with word timestamps where supported, editable caption segments, karaoke-style word highlighting, burned-in MP4, SRT and VTT export.
- **Audio Enhancement:** spectral noise reduction, loudness normalization, voice EQ, trim, fades and volume.
- **Original templates:** Cinematic, Reels/Stories, YouTube Shorts, Travel, Product Showcase, Business, Documentary, Photo Slideshow and Dynamic Montage.
- **Projects / Export Center / Settings:** SQLite-backed project and export history, download links and cleanup.

## Optional models and limits
- **Background removal:** `rembg` + `onnxruntime` are included in requirements. The first segmentation request downloads the selected model (default rembg model); model download requires internet and enough disk space. CPU inference is supported; GPU acceleration is not configured by default.
- **Speech recognition:** Faster-Whisper uses the configured `WHISPER_MODEL` (default `base`) and downloads it once. Choose `tiny` for lower-memory CPU systems. Word-level timings depend on model output.
- **AI upscaling:** no super-resolution model is bundled. Resolution changes use Lanczos resize and do not invent detail.
- **Generative video:** no text-to-video model is bundled. Templates are original editing presets/creative recommendations, not generative video assets.
- **Audio denoising:** FFmpeg `afftdn` is effective on steady noise; aggressive reduction can affect voice quality.
- **Scene and content detection:** video analysis uses sampled frames and heuristics, not semantic object recognition. Template suggestions use duration/aspect/scene heuristics.
- Large media uses disk-backed uploads and asynchronous render jobs. Configure `MAX_UPLOAD_MB` and `DATA_DIR` in `backend/.env` if needed.

## API and tests
Backend API docs: `http://localhost:8000/docs`. Health: `http://localhost:8000/api/health`.
Run frontend tests/build from `frontend`: `npm test` and `npm run build`. Backend integration tests in `tests/backend_check.py` require FFmpeg and the test dependencies described in `tests/README.md`.

### Fix for Auto Captions on fresh installs

The backend pins PyAV to `av>=12,<18` because released Faster-Whisper versions may pass the `metadata_errors` argument removed from PyAV 18+. If you already installed the project before this fix, run `fix_caption_error.bat` once, close the old backend window, and restart with `start.bat`.

If port 8000 is occupied, `start.bat` checks whether it is already a HASSNAIN STUDIO backend. If it belongs to another program, it prints the process ID so you can close that program before restarting.

\n## Caption compatibility and real template rendering

The caption transcription path now includes a compatibility wrapper for Faster-Whisper/PyAV combinations where `metadata_errors` was removed from `av.open`. Re-run `install.bat` to refresh the environment.

Smart Auto Edit now renders the chosen or automatically recommended template with a real aspect-ratio crop (9:16, 1:1, or 16:9), template-specific color treatment, sharpening, denoising, audio cleanup, and silence trimming. The original uploaded video remains unchanged; the rendered result is a separate export.
