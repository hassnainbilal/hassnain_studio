"""HASSNAIN STUDIO backend: FastAPI + FFmpeg + Pillow/OpenCV + optional faster-whisper. Fully local."""
import os, re, json, uuid, sqlite3, subprocess, threading, time, shutil
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(os.getenv("DATA_DIR", Path(__file__).parent / "data")); UP = ROOT / "uploads"; OUT = ROOT / "outputs"
UP.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "4096"))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
IMG = {".jpg", ".jpeg", ".png", ".webp"}; VID = {".mp4", ".mov", ".avi", ".mkv", ".webm"}; AUD = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
FONT = next((f for f in ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"] if os.path.exists(f)), None)
QUAL = {"fast": ("veryfast", 28), "balanced": ("medium", 23), "high": ("slow", 18)}

db = sqlite3.connect(ROOT / "studio.db", check_same_thread=False); dbl = threading.Lock()
db.executescript("""CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,name TEXT,path TEXT,kind TEXT);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT,page TEXT,state TEXT,updated REAL);
CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY,file TEXT,kind TEXT,created REAL);""")
def q(sql, a=(), one=False):
    with dbl:
        c = db.execute(sql, a); db.commit(); r = c.fetchall()
    return (r[0] if r else None) if one else r

for _p in list(OUT.glob("*.trf")) + list(OUT.glob("*_burn.*")) + list(OUT.glob("*cut_tmp*")): _p.unlink(missing_ok=True)  # leftovers from interrupted jobs
app = FastAPI(title="HASSNAIN STUDIO — AI-Powered Image & Video Editing Studio")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/media/outputs", StaticFiles(directory=OUT), name="o"); app.mount("/media/uploads", StaticFiles(directory=UP), name="u")

# ---------- helpers ----------
def esc(p): return str(p).replace("\\", "/").replace(":", "\\:")
def upath(i):
    r = q("SELECT path FROM uploads WHERE id=?", (i,), True)
    if not r or not Path(r[0]).exists(): raise HTTPException(404, f"Uploaded file {i} not found")
    return Path(r[0])
def probe(p):
    try:
        r = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)], capture_output=True, text=True).stdout or "{}")
    except FileNotFoundError: raise HTTPException(500, "FFmpeg/ffprobe not found on PATH")
    v = next((s for s in r.get("streams", []) if s["codec_type"] == "video"), {})
    return {"duration": float(r.get("format", {}).get("duration") or 0), "audio": any(s["codec_type"] == "audio" for s in r.get("streams", [])), "w": v.get("width"), "h": v.get("height")}
def size(aspect, res):
    w, h = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1)}[aspect]; s = res / min(w, h)
    return int(w * s) // 2 * 2, int(h * s) // 2 * 2
def venc(quality): p, c = QUAL.get(quality, QUAL["balanced"]); return ["-c:v", "libx264", "-preset", p, "-crf", str(c), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
def emit(path: Path, kind):
    q("INSERT INTO exports VALUES(?,?,?,?)", (uuid.uuid4().hex, path.name, kind, time.time()))
    return {"name": path.name, "url": f"/media/outputs/{path.name}", "kind": kind}

JOBS = {}
def spawn(kind, fn):
    j = {"id": uuid.uuid4().hex[:10], "kind": kind, "status": "queued", "progress": 0, "error": None, "files": [], "result": None, "cancel": False, "proc": None}
    JOBS[j["id"]] = j
    def run():
        j["status"] = "running"
        try: fn(j); j["status"] = "done"; j["progress"] = 100
        except Exception as e:
            j["status"] = "cancelled" if j["cancel"] else "error"; j["error"] = None if j["cancel"] else str(e)[:600]
    threading.Thread(target=run, daemon=True).start(); return {"job": j["id"]}
def ff(j, args, dur=None, cwd=None):
    p = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-nostats", "-progress", "pipe:1"] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd)
    j["proc"] = p; tail = []
    for l in p.stdout:
        if l.startswith("out_time_us=") and dur:
            try: j["progress"] = min(99, int(int(l.split("=")[1]) / 1e6 / dur * 100))
            except ValueError: pass
        elif not re.match(r"^\w+=\S*$", l.strip()): tail.append(l.strip())
    p.wait()
    if j["cancel"]: raise RuntimeError("cancelled")
    if p.returncode: raise RuntimeError("FFmpeg failed: " + " | ".join(tail[-5:]))
def cap(args):  # run ffmpeg, return stderr (for analysis filters)
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats"] + args, capture_output=True, text=True).stderr
def outp(j, name): return OUT / f"{j['id']}_{name}"
def done(j, path, kind): j["files"].append(emit(path, kind))
def tfmt(t, vtt=False):
    h, r = divmod(int(t * 1000), 3600000); m, r = divmod(r, 60000); s, ms = divmod(r, 1000)
    return f"{h:02}:{m:02}:{s:02}{'.' if vtt else ','}{ms:03}"
def subs(segs, vtt=False):
    o = "WEBVTT\n\n" if vtt else ""
    for i, s in enumerate(segs, 1): o += (f"{i}\n" if not vtt else "") + f"{tfmt(s['start'], vtt)} --> {tfmt(s['end'], vtt)}\n{s['text'].strip()}\n\n"
    return o

# ---------- system / uploads ----------
def whisper_ok():
    try:
        import faster_whisper; return True
    except ImportError: return False
def model_cached():
    try:
        from faster_whisper.utils import download_model; download_model(WHISPER_MODEL, local_files_only=True); return True
    except Exception: return False
@app.get("/api/health")
def health():
    try: import rembg; rb = True
    except ImportError: rb = False
    return {"ffmpeg": bool(shutil.which("ffmpeg")), "whisper_installed": whisper_ok(), "whisper_model": WHISPER_MODEL, "whisper_model_ready": whisper_ok() and model_cached(),
            "rembg": rb, "stabilizer": "vidstab (2-pass)" if HAS_VIDSTAB else "deshake (basic)", "max_upload_mb": MAX_MB, "mode": "HASSNAIN STUDIO · LOCAL MODE", "generative_motion": False}

@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    kind = "image" if ext in IMG else "video" if ext in VID else "audio" if ext in AUD else None
    if not kind: raise HTTPException(400, f"Unsupported format {ext}. Allowed: {sorted(IMG | VID | AUD)}")
    i = uuid.uuid4().hex[:12]; p = UP / f"{i}{ext}"; n = 0
    with open(p, "wb") as f:
        while chunk := await file.read(1 << 20):
            n += len(chunk)
            if n > MAX_MB << 20: f.close(); p.unlink(missing_ok=True); raise HTTPException(413, f"File exceeds {MAX_MB} MB limit")
            f.write(chunk)
    q("INSERT INTO uploads VALUES(?,?,?,?)", (i, file.filename, str(p), kind))
    info = probe(p) if kind != "image" else dict(zip(("w", "h"), Image.open(p).size))
    return {"id": i, "name": file.filename, "kind": kind, "url": f"/media/uploads/{p.name}", **info}

@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str):
    j = JOBS.get(jid)
    if not j: raise HTTPException(404, "No such job")
    j["cancel"] = True
    if j["proc"] and j["proc"].poll() is None: j["proc"].kill()
    return {"ok": True}
@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = JOBS.get(jid)
    if not j: raise HTTPException(404, "No such job")
    return {k: v for k, v in j.items() if k != "proc"}

# ---------- image -> video ----------
class Slide(BaseModel):
    files: list[str]; preset: str = "cinematic"; duration: float = 4; aspect: str = "16:9"; res: int = 1080; fps: int = 30
    transition: float = 0.8; text: str = ""; music: Optional[str] = None; quality: str = "balanced"
MOTION = {"cinematic": ["in", "out"], "slowmo": ["in_s", "out_s"], "pan": ["left", "right"], "kenburns": ["kb_in", "kb_out"], "documentary": ["in_s", "left", "out_s", "right"], "slideshow": ["none"], "reel": ["in_f", "vert"]}
def motion(m, N):
    cx, cy, p = "iw/2-iw/zoom/2", "ih/2-ih/zoom/2", f"on/{N}"
    return {"in": (f"1+0.25*{p}", cx, cy), "in_s": (f"1+0.1*{p}", cx, cy), "in_f": (f"1+0.35*{p}", cx, cy), "out": (f"1.25-0.25*{p}", cx, cy), "out_s": (f"1.1-0.1*{p}", cx, cy),
            "left": ("1.2", f"(iw-iw/zoom)*(1-{p})", cy), "right": ("1.2", f"(iw-iw/zoom)*{p}", cy), "vert": ("1.2", cx, f"(ih-ih/zoom)*{p}"),
            "kb_in": (f"1+0.3*{p}", f"(iw-iw/zoom)*{p}", f"(ih-ih/zoom)*{p}"), "kb_out": (f"1.3-0.3*{p}", f"(iw-iw/zoom)*(1-{p})", f"(ih-ih/zoom)*(1-{p})"), "none": ("1", cx, cy)}[m]
@app.post("/api/image-to-video")
def img2vid(r: Slide):
    paths = [upath(i) for i in r.files]; mus = upath(r.music) if r.music else None
    if not paths: raise HTTPException(400, "Add at least one image")
    W, H = size(r.aspect, r.res); d = max(1.0, r.duration); t = max(0.1, min(r.transition, d / 2)); n = len(paths); N = int((d + t) * r.fps); total = n * d + t
    def fn(j):
        seq = MOTION.get(r.preset, MOTION["cinematic"]); f = ""
        for k in range(n):
            z, x, y = motion(seq[k % len(seq)], N)
            f += f"[{k}:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},setsar=1,zoompan=z='{z}':x='{x}':y='{y}':d={N}:s={W}x{H}:fps={r.fps},format=yuv420p[v{k}];"
        prev = "v0"
        for k in range(1, n): f += f"[{prev}][v{k}]xfade=transition=fade:duration={t}:offset={k*d}[x{k}];"; prev = f"x{k}"
        txt = ""
        if r.text.strip():
            s = r.text.replace("\\", "").replace("'", "’").replace(":", "\\:").replace("%", "\\%")
            txt = f"drawtext=text='{s}':{'fontfile=' + chr(39) + esc(FONT) + chr(39) + ':' if FONT else ''}fontsize={H//16}:fontcolor=white:borderw=3:bordercolor=black:x=(w-tw)/2:y=h*0.84,"
        f += f"[{prev}]{txt}fade=t=in:st=0:d=0.5,fade=t=out:st={total-0.5}:d=0.5[vf]"
        a = []
        for p in paths: a += ["-i", str(p)]
        m = ["-map", "[vf]"]
        if mus: a += ["-stream_loop", "-1", "-i", str(mus)]; m += ["-map", f"{n}:a", "-af", f"afade=t=in:d=1,afade=t=out:st={total-1.5}:d=1.5"]
        o = outp(j, "slideshow.mp4")
        ff(j, a + ["-filter_complex", f, *m, "-r", str(r.fps), "-t", str(total), *venc(r.quality), str(o)], total); done(j, o, "video")
    return spawn("image-to-video", fn)

# ---------- video enhancement / audio ----------
class Enh(BaseModel):
    file: str; brightness: float = 0; contrast: float = 1; saturation: float = 1; sharpness: float = 0; denoise: bool = False; stabilize: bool = False
    audio_denoise: bool = False; denoise_strength: str = "medium"; normalize: bool = False; res: int = 0; fps: int = 0; quality: str = "balanced"; music: Optional[str] = None; music_volume: float = 0.3
def noise_floor(p):
    """Estimate background noise level (dB RMS) as the 10th percentile of 0.5s window levels; afftdn only works when told the real floor."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(p), "-vn", "-af", "asetnsamples=n=22050,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"], capture_output=True, text=True)
    v = sorted(float(x) for x in re.findall(r"RMS_level=(-?\d+\.?\d*)", r.stdout))
    return round(max(-80.0, min(-25.0, v[len(v) // 10])), 1) if v else -50.0
def dn(p, strength="medium"):
    nr = {"low": 12, "medium": 25, "high": 35}.get(strength, 25)
    return f"afftdn=nr={nr}:nf={noise_floor(p)}"
HAS_VIDSTAB = bool(shutil.which("ffmpeg")) and "vidstabdetect" in subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
def vfilters(r, trf=None):
    from video_editor import enhancement_filters
    v = [f"vidstabtransform=input={trf}:smoothing=15" if trf else "deshake"] if r.stabilize else []
    v += enhancement_filters(r.brightness, r.contrast, r.saturation, r.sharpness, r.denoise)
    if r.res: v.append(f"scale=-2:{r.res}:flags=lanczos")  # plain resize, NOT AI upscaling
    if r.fps: v.append(f"fps={r.fps}")
    return v
def afilters(r, src=None): return ([dn(src, r.denoise_strength)] if r.audio_denoise else []) + (["loudnorm=I=-16:TP=-1.5"] if r.normalize else [])
@app.post("/api/video/enhance")
def enhance(r: Enh):
    src = upath(r.file); info = probe(src); mus = upath(r.music) if r.music else None
    def fn(j):
        o = outp(j, "enhanced.mp4"); trf = None
        try:
            if r.stabilize and HAS_VIDSTAB:
                trf = f"{j['id']}.trf"; ff(j, ["-i", str(src), "-vf", f"vidstabdetect=shakiness=5:result={trf}", "-an", "-f", "null", "-"], info["duration"], cwd=OUT)
            v, au = vfilters(r, trf), afilters(r, src)
            if mus:  # mix looped background music under the original sound
                parts = [f"[0:v]{','.join(v) or 'null'}[v]"]
                if info["audio"]: parts += [f"[0:a]{','.join(au) or 'anull'}[a0]", f"[1:a]volume={r.music_volume}[m]", "[a0][m]amix=inputs=2:duration=first:normalize=0[a]"]
                else: parts += [f"[1:a]volume={r.music_volume}[a]"]
                a = ["-i", str(src), "-stream_loop", "-1", "-i", str(mus), "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", "-t", str(info["duration"])]
            else:
                a = ["-i", str(src)] + (["-vf", ",".join(v)] if v else []) + (["-af", ",".join(au)] if au and info["audio"] else [])
            ff(j, a + venc(r.quality) + [str(o)], info["duration"], cwd=OUT)
        finally:
            if trf: (OUT / trf).unlink(missing_ok=True)
        done(j, o, "video")
    return spawn("video-enhance", fn)

class Aud(BaseModel):
    file: str; denoise: bool = True; denoise_strength: str = "medium"; normalize: bool = True; voice: bool = False; volume: float = 1; fade_in: float = 0; fade_out: float = 0; start: float = 0; end: float = 0
@app.post("/api/audio/enhance")
def audio(r: Aud):
    src = upath(r.file); info = probe(src)
    if not info["audio"]: raise HTTPException(400, "This file has no audio track")
    def fn(j):
        dur = (r.end or info["duration"]) - r.start; f = []
        if r.denoise: f.append(dn(src, r.denoise_strength))
        if r.voice: f.append("highpass=f=80,lowpass=f=12000,equalizer=f=3000:t=q:w=1:g=3")
        if r.volume != 1: f.append(f"volume={r.volume}")
        if r.normalize: f.append("loudnorm=I=-16:TP=-1.5")
        if r.fade_in: f.append(f"afade=t=in:d={r.fade_in}")
        if r.fade_out: f.append(f"afade=t=out:st={max(0, dur - r.fade_out)}:d={r.fade_out}")
        o = outp(j, "enhanced.m4a"); a = (["-ss", str(r.start)] if r.start else []) + (["-t", str(dur)] if r.end else []) + ["-i", str(src), "-vn"]
        if f: a += ["-af", ",".join(f)]
        ff(j, a + ["-c:a", "aac", "-b:a", "192k", str(o)], dur); done(j, o, "audio")
    return spawn("audio-enhance", fn)

# ---------- captions helpers ----------
def run_whisper(path, language=None, j=None):
    # Compatibility for Faster-Whisper/PyAV: newer PyAV removed metadata_errors.
    import av
    _original_av_open = av.open
    if not getattr(av.open, "_hassnain_metadata_compat", False):
        def _compatible_av_open(*args, **kwargs):
            kwargs.pop("metadata_errors", None)
            return _original_av_open(*args, **kwargs)
        _compatible_av_open._hassnain_metadata_compat = True
        av.open = _compatible_av_open
    from faster_whisper import WhisperModel
    m = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8"); it, info = m.transcribe(str(path), vad_filter=True, language=language or None, word_timestamps=True); segs = []
    for s in it:
        segs.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(), "words": [{"w": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)} for w in (s.words or [])]})
        if j: j["progress"] = min(99, int(s.end / max(info.duration, 1) * 100))
    return info.language, segs
STY = {"tiktok": (26, 1, 3, 0, "FFFFFF", 5), "reel": (24, 1, 2, 1, "FFFFFF", 2), "shorts": (22, 1, 0, 0, "FFFFFF", 2), "professional": (18, 0, 1, 0, "FFFFFF", 2), "cinematic": (17, 0, 1, 1, "F2E6C9", 2), "minimal": (15, 0, 0, 0, "FFFFFF", 2)}
def bgr(h): h = h.lstrip("#"); return h[4:6] + h[2:4] + h[0:2]
def ass_text(segs, W, H, size, bold, outl, col, hi, al):
    t = lambda x: "%d:%02d:%02d.%02d" % (x // 3600, x % 3600 // 60, x % 60, int(x * 100) % 100)
    out = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
           "Style: D,Arial,%d,&H00%s,&H00%s,&H00000000,&H80000000,%d,0,0,0,100,100,0,0,1,%d,0,%d,40,40,%d,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
           % (W, H, int(size * H / 288 * .9), bgr(hi), bgr(col), bold, max(1, int(outl * H / 288 * .6)), al, int(H * .06)))
    for s in segs:  # karaoke: words switch from base colour to highlight colour as they are spoken
        if s.get("words"):
            prev, txt = s["start"], ""
            for w in s["words"]:
                txt += "{\\k%d}{\\kf%d}%s " % (max(0, int((w["start"] - prev) * 100)), max(1, int((w["end"] - w["start"]) * 100)), w["w"].replace("{", "").replace("}", "")); prev = w["end"]
        else: txt = s["text"].replace("{", "").replace("}", "")
        out += "Dialogue: 0,%s,%s,D,,0,0,0,,%s\n" % (t(s["start"]), t(s["end"]), txt.strip().replace("\n", "\\N"))
    return out
def burn_job(j, src, segs, st, quality="balanced", name="captioned.mp4"):
    info = probe(src); size_, bold, outl, box, col, al = STY.get(st.get("preset", "professional"), STY["professional"])
    size_ = st.get("size") or size_; col = (st.get("color") or col).lstrip("#"); al = {"bottom": 2, "middle": 5, "top": 8}.get(st.get("position"), al)
    kar = bool(st.get("highlight")) and any(g.get("words") for g in segs); o = outp(j, name)
    sp = OUT / f"{j['id']}_burn.{'ass' if kar else 'srt'}"
    try:
        if kar: sp.write_text(ass_text(segs, info["w"], info["h"], size_, bold, outl, col, st.get("highlight_color") or "FFE600", al), encoding="utf-8"); vf = f"ass={sp.name}"
        else:
            sp.write_text(subs(segs), encoding="utf-8")
            vf = f"subtitles={sp.name}:force_style='Fontsize={size_},Bold={bold},Outline={outl},Shadow={box},PrimaryColour=&H00{bgr(col)}&,Alignment={al},MarginV=24" + (",BorderStyle=3,BackColour=&H80000000&'" if st.get("preset") == "shorts" else "'")
        ff(j, ["-i", str(src), "-vf", vf] + venc(quality) + [str(o)], info["duration"], cwd=OUT)
    finally: sp.unlink(missing_ok=True)
    return o

# ---------- auto edit ----------
@app.post("/api/autoedit/analyze")
def analyze(body: dict):
    src = upath(body["file"]); info = probe(src)
    def fn(j):
        sil, cuts = [], []
        if info["audio"]:
            s = None
            for l in cap(["-i", str(src), "-af", "silencedetect=noise=-30dB:d=0.8", "-f", "null", "-"]).splitlines():
                if m := re.search(r"silence_start: ([\d.]+)", l): s = float(m[1])
                if (m := re.search(r"silence_end: ([\d.]+)", l)) and s is not None: sil.append([s, float(m[1])]); s = None
            if s is not None: sil.append([s, info["duration"]])
            cuts = [{"start": round(a + .3, 2), "end": round(b - .3, 2)} for a, b in sil if b - a >= 1.3]
        j["progress"] = 50
        sc = [float(x) for x in re.findall(r"pts_time:([\d.]+)", cap(["-i", str(src), "-vf", "select='gt(scene,0.4)',showinfo", "-an", "-f", "null", "-"]))]
        j["result"] = {"duration": info["duration"], "silences": sil, "scenes": sc, "suggested_cuts": cuts}
    return spawn("analyze", fn)
class AutoEdit(BaseModel):
    file: str; cuts: list[dict] = []; enhance: bool = True; audio: bool = True; quality: str = "balanced"; captions: bool = False; preset: str = "reel"
@app.post("/api/autoedit/render")
def autoedit(r: AutoEdit):
    src = upath(r.file); info = probe(src)
    if r.captions and not (whisper_ok() and model_cached()): raise HTTPException(409, "Captions need Faster-Whisper and its model. Set them up on the Auto Captions page, or turn captions off.")
    def fn(j):
        v, a = [], []
        if r.cuts:
            e = "+".join(f"between(t,{c['start']},{c['end']})" for c in r.cuts)
            v.append(f"select='not({e})',setpts=N/FRAME_RATE/TB"); a.append(f"aselect='not({e})',asetpts=N/SR/TB")
        if r.enhance: v += ["hqdn3d=2:1.5:3:3", "eq=contrast=1.05:saturation=1.1:brightness=0.02", "unsharp=5:5:0.4"]
        if r.audio: a += [dn(src), "loudnorm=I=-16:TP=-1.5"]
        args = ["-i", str(src)] + (["-vf", ",".join(v)] if v else []) + (["-af", ",".join(a)] if a and info["audio"] else [])
        o = outp(j, "cut_tmp.mp4" if r.captions else "autoedit.mp4"); ff(j, args + venc(r.quality) + [str(o)], info["duration"])
        if not r.captions: done(j, o, "video"); return
        try:
            j["stage"] = "recognizing speech"; lang, segs = run_whisper(o, j=j); j["stage"] = "burning captions"
            done(j, burn_job(j, o, segs, {"preset": r.preset, "highlight": True}, r.quality, "autoedit_captioned.mp4"), "video"); j["result"] = {"language": lang, "segments": segs}
        finally: o.unlink(missing_ok=True)
    return spawn("autoedit", fn)

# ---------- captions ----------
@app.post("/api/models/download")
def dl_model():
    if not whisper_ok(): raise HTTPException(400, "faster-whisper is not installed. Run: pip install faster-whisper")
    def fn(j):
        from faster_whisper.utils import download_model; j["progress"] = None; download_model(WHISPER_MODEL)
    return spawn("model-download", fn)
@app.post("/api/captions/transcribe")
def transcribe(body: dict):
    src = upath(body["file"])
    if not whisper_ok(): raise HTTPException(400, "faster-whisper is not installed. Run: pip install faster-whisper")
    if not model_cached(): raise HTTPException(409, "Speech model not downloaded yet. Use the setup button first.")
    def fn(j): lang, segs = run_whisper(src, body.get("language"), j); j["result"] = {"language": lang, "segments": segs}
    return spawn("transcribe", fn)
@app.post("/api/captions/export")
def cap_export(body: dict):
    fmt = body["fmt"]; p = OUT / f"{uuid.uuid4().hex[:8]}_captions.{fmt}"
    p.write_text(subs(body["segments"], fmt == "vtt"), encoding="utf-8"); return emit(p, "subtitle")
@app.post("/api/captions/burn")
def burn(body: dict):
    src = upath(body["file"])
    def fn(j): done(j, burn_job(j, src, body["segments"], body, body.get("quality", "balanced")), "video")
    return spawn("burn-captions", fn)
@app.post("/api/cleanup")
def cleanup(body: dict):
    cut = time.time() - float(body.get("days", 7)) * 86400; n = 0
    for d in (UP, OUT):
        for p in d.iterdir():
            if p.is_file() and p.stat().st_mtime < cut: p.unlink(missing_ok=True); n += 1
    q("DELETE FROM uploads WHERE path NOT IN (%s)" % ",".join("?" * len(list(UP.iterdir()))) if list(UP.iterdir()) else "DELETE FROM uploads", [str(p) for p in UP.iterdir()])
    return {"deleted": n}


# ---------- diagnostics and smart workflows ----------
@app.post("/api/image/analyze")
def image_analyze(body: dict):
    from image_analyzer import analyze_image
    src = upath(body["file"])
    try:
        with Image.open(src) as im: return analyze_image(im)
    except Exception as e: raise HTTPException(400, f"Could not analyze image: {e}")

@app.post("/api/image/auto-enhance")
def image_auto_enhance(body: dict):
    from image_analyzer import auto_enhance
    src = upath(body["file"])
    try:
        with Image.open(src) as im: result, report = auto_enhance(im)
        p = OUT / f"{uuid.uuid4().hex[:8]}_auto_enhanced.png"; result.save(p, format="PNG", optimize=True)
        out = emit(p, "image"); out["analysis"] = report; return out
    except Exception as e: raise HTTPException(400, f"Could not enhance image: {e}")

@app.post("/api/image/remove-background")
def image_remove_background(body: dict):
    src = upath(body["file"])
    try:
        from rembg import remove
    except ImportError: raise HTTPException(501, "Background removal is not installed. Run: pip install rembg onnxruntime")
    try:
        with Image.open(src) as im: result = remove(ImageOps.exif_transpose(im).convert("RGBA"))
        p = OUT / f"{uuid.uuid4().hex[:8]}_background_removed.png"; result.save(p, "PNG", optimize=True)
        return emit(p, "image")
    except Exception as e: raise HTTPException(500, f"Background removal failed: {e}")

VIDEO_TEMPLATES = [
 {"id":"cinematic","name":"Cinematic","aspect":"16:9","description":"Wide framing, gentle motion and restrained color"},
 {"id":"reels","name":"Reels and Instagram Stories","aspect":"9:16","description":"Vertical social-first framing"},
 {"id":"shorts","name":"YouTube Shorts","aspect":"9:16","description":"Vertical short-form pacing"},
 {"id":"travel","name":"Travel","aspect":"16:9","description":"Scenic montage and smooth transitions"},
 {"id":"product","name":"Product Showcase","aspect":"1:1","description":"Centered product framing and clean cuts"},
 {"id":"business","name":"Business","aspect":"16:9","description":"Clean professional presentation"},
 {"id":"documentary","name":"Documentary","aspect":"16:9","description":"Natural color and deliberate pacing"},
 {"id":"slideshow","name":"Photo Slideshow","aspect":"16:9","description":"Photo-led motion and crossfades"},
 {"id":"montage","name":"Dynamic Montage","aspect":"9:16","description":"Fast-paced vertical sequence"}]

@app.post("/api/video/smart-workflow")
def smart_video_workflow(body: dict):
    src = upath(body["file"]); info = probe(src)
    quality = body.get("quality", "balanced")
    def fn(j):
        from video_analyzer import analyze_video
        analysis = analyze_video(src); silences = []
        if info["audio"]:
            st = None
            for line in cap(["-i", str(src), "-af", "silencedetect=noise=-30dB:d=0.8", "-f", "null", "-"]).splitlines():
                if m := re.search(r"silence_start: ([\\d.]+)", line): st = float(m[1])
                if (m := re.search(r"silence_end: ([\\d.]+)", line)) and st is not None:
                    if float(m[1]) - st >= 1.3: silences.append([st, float(m[1])])
                    st = None
        cuts = [{"start": round(a+.25,2), "end": round(b-.25,2)} for a,b in silences if b-a >= 1.3 and b-.25 > a+.25]
        requested = str(body.get("template") or "auto").strip().lower()
        names = {"cinematic":"Cinematic","reels":"Reels and Instagram Stories",
          "reels and instagram stories":"Reels and Instagram Stories","shorts":"YouTube Shorts",
          "youtube shorts":"YouTube Shorts","travel":"Travel","product":"Product Showcase",
          "product showcase":"Product Showcase","business":"Business","documentary":"Documentary",
          "slideshow":"Photo Slideshow","montage":"Dynamic Montage","dynamic montage":"Dynamic Montage"}
        selected = analysis["recommended_template"] if requested in ("", "auto", "automatic") else names.get(requested, analysis["recommended_template"])
        aspect = "9:16" if selected in ("Reels and Instagram Stories","YouTube Shorts","Dynamic Montage") else "1:1" if selected == "Product Showcase" else "16:9"
        tw, th = {"9:16":(1080,1920),"1:1":(1080,1080),"16:9":(1920,1080)}[aspect]
        looks = {"Cinematic":"eq=contrast=1.12:saturation=0.92:brightness=-0.01",
          "Reels and Instagram Stories":"eq=contrast=1.08:saturation=1.16:brightness=0.015",
          "YouTube Shorts":"eq=contrast=1.08:saturation=1.12:brightness=0.01",
          "Travel":"eq=contrast=1.08:saturation=1.20:brightness=0.015",
          "Product Showcase":"eq=contrast=1.10:saturation=1.08:brightness=0.01",
          "Business":"eq=contrast=1.04:saturation=0.96:brightness=0.005",
          "Documentary":"eq=contrast=1.05:saturation=0.98:brightness=0.005",
          "Photo Slideshow":"eq=contrast=1.06:saturation=1.08:brightness=0.01",
          "Dynamic Montage":"eq=contrast=1.13:saturation=1.20:brightness=0.02"}[selected]
        vf = ["hqdn3d=2:1.5:3:3", looks,
              f"scale={tw}:{th}:force_original_aspect_ratio=increase:flags=lanczos",
              f"crop={tw}:{th}", "setsar=1", "unsharp=5:5:0.45"]
        af = [dn(src), "loudnorm=I=-16:TP=-1.5"] if info["audio"] else []
        args = ["-i", str(src)]
        if cuts:
            expr = "+".join(f"between(t,{c['start']},{c['end']})" for c in cuts)
            vf.insert(0, f"select='not({expr})',setpts=N/FRAME_RATE/TB")
            if info["audio"]: af.insert(0, f"aselect='not({expr})',asetpts=N/SR/TB")
        o = outp(j, "smart_edit.mp4")
        ff(j, args + ["-vf", ",".join(vf)] + (["-af", ",".join(af)] if af else []) +
           ["-map","0:v:0"] + (["-map","0:a:0?"] if not af else []) + venc(quality) + [str(o)], info["duration"])
        j["result"] = {"analysis":analysis,"recommended_template":analysis["recommended_template"],
          "applied_template":selected,"output_aspect":aspect,"removed_silences":len(cuts),"captions_added":False}
        if body.get("captions") and info["audio"] and whisper_ok() and model_cached():
            j["stage"]="generating word-timed captions"; lang,segs=run_whisper(o,j=j)
            j["stage"]="burning captions"; preset="reel" if aspect=="9:16" else "cinematic"
            captioned=burn_job(j,o,segs,{"preset":preset,"highlight":True},quality,"smart_captioned.mp4")
            o.unlink(missing_ok=True); o=captioned
            j["result"].update({"language":lang,"captions_added":True})
        done(j,o,"video")
    return spawn("smart-video-workflow",fn)

@app.get("/api/video/templates")
def video_templates(): return VIDEO_TEMPLATES

@app.post("/api/video/analyze")
def video_analyze(body: dict):
    from video_analyzer import analyze_video
    try: return analyze_video(upath(body["file"]))
    except FileNotFoundError: raise HTTPException(500, "FFmpeg/ffprobe and OpenCV are required for video analysis")
    except Exception as e: raise HTTPException(400, f"Could not analyze video: {e}")

# ---------- image editor ----------
class ImgEdit(BaseModel):
    file: str; brightness: float = 1; contrast: float = 1; saturation: float = 1; sharpness: float = 1; blur: float = 0; denoise: bool = False
    rotate: int = 0; flip_h: bool = False; flip_v: bool = False; crop: Optional[list[float]] = None; width: int = 0; filter: str = "none"; fmt: str = "png"; remove_bg: bool = False
@app.post("/api/image/edit")
def img_edit(r: ImgEdit):
    im = ImageOps.exif_transpose(Image.open(upath(r.file))).convert("RGBA")
    if r.remove_bg:
        try: from rembg import remove
        except ImportError: raise HTTPException(501, "Background removal needs the optional model: pip install rembg onnxruntime")
        im = remove(im)
    if r.crop: w, h = im.size; l, t, rr, b = r.crop; im = im.crop((int(l * w), int(t * h), int(rr * w), int(b * h)))
    if r.rotate: im = im.rotate(-r.rotate, expand=True)
    if r.flip_h: im = ImageOps.mirror(im)
    if r.flip_v: im = ImageOps.flip(im)
    if r.width: im = im.resize((r.width, int(im.height * r.width / im.width)), Image.LANCZOS)
    alpha = im.getchannel("A"); rgb = im.convert("RGB")
    if r.denoise:
        import cv2, numpy as np
        rgb = Image.fromarray(cv2.cvtColor(cv2.fastNlMeansDenoisingColored(cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR), None, 6, 6, 7, 21), cv2.COLOR_BGR2RGB))
    for E, v in ((ImageEnhance.Brightness, r.brightness), (ImageEnhance.Contrast, r.contrast), (ImageEnhance.Color, r.saturation), (ImageEnhance.Sharpness, r.sharpness)):
        if v != 1: rgb = E(rgb).enhance(v)
    if r.blur: rgb = rgb.filter(ImageFilter.GaussianBlur(r.blur))
    if r.filter == "grayscale": rgb = ImageOps.grayscale(rgb).convert("RGB")
    elif r.filter == "sepia": rgb = ImageOps.colorize(ImageOps.grayscale(rgb), "#2b1a0a", "#f4e2c0")
    elif r.filter in ("warm", "cool"):
        R, G, B = rgb.split(); k = 1.12 if r.filter == "warm" else 0.9
        rgb = Image.merge("RGB", (R.point(lambda x: min(255, int(x * k))), G, B.point(lambda x: min(255, int(x * (2 - k))))))
    ext = {"png": "png", "jpg": "jpg", "webp": "webp"}[r.fmt]; p = OUT / f"{uuid.uuid4().hex[:8]}_edited.{ext}"
    if ext == "jpg":
        rgb.save(p, quality=92)
    else:
        rgb = rgb.convert("RGBA"); rgb.putalpha(alpha); rgb.save(p, quality=92)
    return emit(p, "image")  # original upload is never modified

# ---------- social (template based, NOT AI) ----------
STOP = set("the a an and or but if so to of in on at for with is are was were be been it this that these those i you he she we they my your our their as by from not have has had do does did will would can could just like very really about into than then there here what when which who how".split())
@app.post("/api/social")
def social(body: dict):
    t = body.get("transcript", "").strip()
    if not t: raise HTTPException(400, "Paste or generate a transcript first")
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]; words = [w for w in re.findall(r"[A-Za-z']{4,}", t.lower()) if w not in STOP]
    top = [w for w, _ in sorted({w: words.count(w) for w in set(words)}.items(), key=lambda x: -x[1])[:8]]; tags = " ".join("#" + w.replace("'", "") for w in top[:6])
    head = sents[0][:70].rstrip(".!?") if sents else t[:70]; summ = " ".join(sents[:3])
    return {"generated_by": "template (no language model used)", "youtube_title": head, "youtube_description": f"{summ}\n\nTopics: {', '.join(top)}\n\n{tags}",
            "instagram": f"{head} ✨\n\n{tags}", "tiktok": f"{head} {' '.join(tags.split()[:4])}", "facebook": f"{head}\n\n{summ[:240]}", "hashtags": tags, "summary": summ, "thumbnail_text": " ".join(head.split()[:4]).upper()}

# ---------- projects / exports ----------
@app.get("/api/projects")
def plist(): return [{"id": r[0], "name": r[1], "page": r[2], "state": json.loads(r[3]), "updated": r[4]} for r in q("SELECT * FROM projects ORDER BY updated DESC")]
@app.post("/api/projects")
def psave(b: dict):
    i = b.get("id") or uuid.uuid4().hex[:10]; q("INSERT OR REPLACE INTO projects VALUES(?,?,?,?,?)", (i, b["name"], b["page"], json.dumps(b["state"]), time.time())); return {"id": i}
@app.delete("/api/projects/{i}")
def pdel(i: str): q("DELETE FROM projects WHERE id=?", (i,)); return {"ok": True}
@app.get("/api/exports")
def elist(): return [{"name": r[1], "url": f"/media/outputs/{r[1]}", "kind": r[2], "created": r[3]} for r in q("SELECT * FROM exports ORDER BY created DESC LIMIT 200") if (OUT / r[1]).exists()]
