"""ClipVox core pipeline.

YouTube link or local audio file
  -> download (yt-dlp)
  -> optional music/noise removal (Demucs, runs on CPU)
  -> clean-up (high-pass, trim long silences, even out volume)
  -> TikTrigz voice format: WAV, 16-bit PCM, mono, 22,050 Hz
  -> split into clips under the size/length limits
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

# ---- TikTrigz voice limits -------------------------------------------------
TARGET_RATE = 22050          # Hz
TARGET_CHANNELS = 1          # mono
TARGET_SAMPLE_WIDTH = 2      # bytes -> 16-bit
MAX_CLIPS = 20
MAX_CLIP_BYTES = 12 * 1024 * 1024
MAX_CLIP_SECONDS = 300       # "under ~5 minutes"
CLIP_SECONDS = 240           # 4 min -> ~10.6 MB, safely under both limits
MIN_CLIP_SECONDS = 2.0       # tiny leftovers are dropped

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus",
              ".webm", ".mp4", ".mkv", ".mov", ".wma"}

Log = Callable[[str], None]


@dataclass
class Options:
    remove_music: bool = True
    trim_silence: bool = True
    normalize: bool = True
    clip_seconds: int = CLIP_SECONDS
    speaker_only: bool = False          # keep only the wanted voice
    speaker_sample: str | None = None   # optional voice sample file
    speaker_max_minutes: float | None = 30


def ffmpeg_exe() -> str:
    """Use ffmpeg from PATH, else the copy bundled with imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("ffmpeg not found. Run install.bat again.") from exc


def _run(cmd: list[str]) -> None:
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW on Windows
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", creationflags=flags)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg failed:\n{tail}")


def safe_name(text: str, fallback: str = "voice") -> str:
    text = re.sub(r"[^A-Za-z0-9 _-]+", "", text).strip().replace(" ", "_")
    return (text[:48] or fallback)


def is_url(text: str) -> bool:
    return bool(re.match(r"^https?://[^\s]+$", text.strip(), re.I))


# ---- Step 1: download -------------------------------------------------------
def download_audio(url: str, workdir: Path, log: Log) -> tuple[Path, str]:
    if not is_url(url):
        raise ValueError(f"Not a web link: {url}")
    import yt_dlp

    log(f"Downloading audio: {url}")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(workdir / "dl_%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": ffmpeg_exe(),
        "restrictfilenames": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    if not path.exists():  # yt-dlp sometimes changes the extension
        matches = list(workdir.glob(f"dl_{info.get('id')}.*"))
        if not matches:
            raise RuntimeError("Download finished but the file was not found.")
        path = matches[0]
    title = info.get("title") or info.get("id") or "voice"
    log(f"  got: {title}")
    return path, title


# ---- Step 2: music / noise removal -----------------------------------------
_MODEL = None


def _load_model(log: Log):
    global _MODEL
    if _MODEL is None:
        from demucs.pretrained import get_model
        log("Loading the vocal-separation model (first time downloads ~80 MB)...")
        _MODEL = get_model("htdemucs")
        _MODEL.eval()
    return _MODEL


def separate_vocals(src_wav: Path, dst_wav: Path, log: Log, model=None) -> None:
    """Keep only the voice. Input must be 44.1 kHz stereo WAV."""
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model

    model = model or _load_model(log)
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    data, rate = sf.read(str(src_wav), dtype="float32", always_2d=True)
    if rate != model.samplerate:
        raise RuntimeError(f"Expected {model.samplerate} Hz, got {rate} Hz")
    wav = torch.from_numpy(np.ascontiguousarray(data.T))
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    wav = (wav - mean) / std
    minutes = data.shape[0] / rate / 60
    log(f"Removing music/noise from {minutes:.1f} min of audio "
        f"(CPU, can take a few minutes)...")
    with torch.no_grad():
        sources = apply_model(model, wav[None], device="cpu", split=True,
                              overlap=0.25, progress=False)[0]
    vocals = sources[model.sources.index("vocals")] * std + mean
    sf.write(str(dst_wav), vocals.numpy().T, rate, subtype="PCM_16")


# ---- Step 3+4: clean, convert, split ---------------------------------------
def _filter_chain(opts: Options) -> str:
    parts = ["highpass=f=70"]
    if opts.trim_silence:
        # Shorten any silence longer than 0.7 s down to 0.3 s.
        parts.append("silenceremove=stop_periods=-1:stop_duration=0.7:"
                     "stop_threshold=-45dB:stop_silence=0.3")
    if opts.normalize:
        parts.append("loudnorm=I=-18:TP=-2:LRA=11")
    parts.append(f"aresample={TARGET_RATE}")
    return ",".join(parts)


def convert_and_split(src: Path, out_dir: Path, base: str, opts: Options,
                      start_index: int, log: Log) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    seconds = max(10, min(int(opts.clip_seconds), MAX_CLIP_SECONDS - 10))
    seg_dir = Path(tempfile.mkdtemp(prefix="seg_", dir=src.parent))
    _run([ffmpeg_exe(), "-hide_banner", "-y", "-i", str(src),
          "-vn", "-af", _filter_chain(opts),
          "-ac", str(TARGET_CHANNELS), "-ar", str(TARGET_RATE),
          "-c:a", "pcm_s16le", "-map_metadata", "-1",
          "-f", "segment", "-segment_time", str(seconds),
          "-segment_format", "wav", "-reset_timestamps", "1",
          str(seg_dir / "part_%03d.wav")])
    kept = []
    n = start_index
    for part in sorted(seg_dir.glob("part_*.wav")):
        if check_clip(part)["seconds"] < MIN_CLIP_SECONDS:
            continue
        while (out_dir / f"{base}_{n:02d}.wav").exists():  # never overwrite
            n += 1
        dest = out_dir / f"{base}_{n:02d}.wav"
        shutil.move(str(part), str(dest))
        kept.append(dest)
        n += 1
    shutil.rmtree(seg_dir, ignore_errors=True)
    return kept


def check_clip(path: Path) -> dict:
    """Read the WAV header and confirm it meets the TikTrigz format."""
    with wave.open(str(path), "rb") as w:
        info = {
            "rate": w.getframerate(),
            "channels": w.getnchannels(),
            "bits": w.getsampwidth() * 8,
            "seconds": w.getnframes() / float(w.getframerate()),
            "bytes": path.stat().st_size,
        }
    info["ok"] = (info["rate"] == TARGET_RATE and info["channels"] == 1
                  and info["bits"] == 16 and info["bytes"] <= MAX_CLIP_BYTES
                  and info["seconds"] <= MAX_CLIP_SECONDS)
    return info


# ---- Whole job --------------------------------------------------------------
def to_stereo_44k(src: Path, dst: Path) -> None:
    _run([ffmpeg_exe(), "-hide_banner", "-y", "-i", str(src), "-vn",
          "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dst)])


def process(sources: Iterable[str], out_dir: Path, opts: Options, log: Log,
            name: str | None = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="clipvox_") as tmp:
        tmp = Path(tmp)
        for i, item in enumerate([s.strip() for s in sources if s.strip()]):
            if len(made) >= MAX_CLIPS:
                log(f"Reached the {MAX_CLIPS}-clip limit; skipping the rest.")
                break
            try:
                if is_url(item):
                    raw, title = download_audio(item, tmp, log)
                else:
                    raw = Path(item.strip('"'))
                    if not raw.is_file():
                        raise FileNotFoundError(f"File not found: {raw}")
                    if raw.suffix.lower() not in AUDIO_EXTS:
                        raise ValueError(f"Not an audio/video file: {raw.name}")
                    title = raw.stem
                    log(f"Using file: {raw.name}")
                base = safe_name(name or title)
                if name:
                    base = f"{base}_{i + 1}"
                work = tmp / f"src_{i}.wav"
                to_stereo_44k(raw, work)
                if opts.speaker_only:
                    import clipvox_speaker as spk
                    sample = Path(opts.speaker_sample) if opts.speaker_sample else None
                    log("Finding when the wanted voice is talking...")
                    res = spk.find_speaker(work, log, sample=sample,
                                           max_minutes=opts.speaker_max_minutes)
                    if not res.segments:
                        raise RuntimeError("Could not find the wanted voice. "
                                           + (res.note or ""))
                    only = tmp / f"spk_{i}.wav"
                    kept = spk.keep_segments(work, only, res.segments)
                    log(f"  kept {kept / 60:.1f} min of the wanted voice "
                        f"({res.voices} voice(s) heard, picked by {res.picked_by}, "
                        f"confidence {res.confidence})")
                    work = only
                if opts.remove_music:
                    voc = tmp / f"voc_{i}.wav"
                    separate_vocals(work, voc, log)
                    work = voc
                log("Converting to 16-bit / mono / 22,050 Hz and splitting...")
                clips = convert_and_split(work, out_dir, base, opts, 1, log)
                room = MAX_CLIPS - len(made)
                if len(clips) > room:
                    for extra in clips[room:]:
                        extra.unlink()
                    clips = clips[:room]
                    log(f"Trimmed to stay at {MAX_CLIPS} clips total.")
                for c in clips:
                    info = check_clip(c)
                    log(f"  {c.name}: {info['seconds']:.0f}s, "
                        f"{info['bytes'] / 1048576:.1f} MB "
                        f"{'OK' if info['ok'] else 'CHECK FAILED'}")
                made.extend(clips)
            except Exception as exc:
                log(f"ERROR with {item}: {exc}")
    log(f"Done. {len(made)} clip(s) in {out_dir}")
    return made
