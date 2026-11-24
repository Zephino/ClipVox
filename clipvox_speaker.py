"""ClipVox speaker finder: work out *when* the wanted person is talking.

How it works (all on your CPU, no accounts or keys):
  1. Find the parts of the audio that are speech (Silero VAD).
  2. Take a "voice fingerprint" of every 1.5-second slice of speech
     (SpeechBrain ECAPA speaker model).
  3. Group slices that sound like the same person.
  4. Pick the wanted person:
       - with a voice sample: the group that sounds most like the sample,
       - without one: the group that talks the most (the guest in an interview).
  5. Join that person's slices into time ranges like 0:12-0:45.

Batch mode reads the CSV you download from the sheet's "Needs Trimming" page and
writes a timestamps CSV, one row per video, saving after every video so you can
stop and pick up where you left off.
"""

from __future__ import annotations

import csv
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import clipvox_core as core

Log = Callable[[str], None]

SR = 16000             # analysis sample rate
WIN = 1.5              # seconds per fingerprint slice
HOP = 0.75             # step between slices
MIN_REGION = 0.4       # ignore speech blips shorter than this
MIN_SEG = 1.0          # drop final ranges shorter than this
JOIN_GAP = 0.6         # join ranges separated by less than this
PAD = 0.1              # small cushion around each range
GROUP_THRESHOLD = 0.55 # how different two voices must be to split (cosine distance)
SAMPLE_MATCH = 0.45    # how close a group must be to the sample (cosine similarity)
MIN_GROUP_SHARE = 0.03 # groups with less than 3% of the talking are treated as noise
DEFAULT_MAX_MINUTES = 20

APP_DIR = Path(__file__).resolve().parent
MODEL_DIR = APP_DIR / "models" / "ecapa"

OUT_FIELDS = ["Character", "Show", "URL", "Timestamps", "Wanted speech",
              "Voices found", "Picked by", "Confidence", "Jump to first", "Note"]


@dataclass
class Result:
    segments: list[tuple[float, float]]
    voices: int
    target_seconds: float
    speech_seconds: float
    picked_by: str       # "most talking" or "voice sample"
    confidence: str      # high / medium / low
    note: str = ""


# ---- models (loaded once) ----------------------------------------------------
_VAD = None
_ENC = None


def _vad(log: Log):
    global _VAD
    if _VAD is None:
        from silero_vad import load_silero_vad
        log("Loading the speech detector...")
        _VAD = load_silero_vad()
    return _VAD


def _encoder(log: Log):
    global _ENC
    if _ENC is None:
        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError:  # older SpeechBrain
            from speechbrain.pretrained import EncoderClassifier
        kwargs = {}
        try:  # Windows can't always make symlinks: copy the files instead
            from speechbrain.utils.fetching import LocalStrategy
            kwargs["local_strategy"] = LocalStrategy.COPY
        except Exception:
            pass
        log("Loading the voice-fingerprint model (first time downloads ~85 MB)...")
        _ENC = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(MODEL_DIR), run_opts={"device": "cpu"}, **kwargs)
    return _ENC


# ---- audio helpers -----------------------------------------------------------
def load_16k(src: Path, tmp: Path, max_minutes: float | None = None):
    """Decode any audio/video file to 16 kHz mono float32 numpy array."""
    import soundfile as sf
    dst = tmp / f"a16_{abs(hash(str(src)))}.wav"
    cmd = [core.ffmpeg_exe(), "-hide_banner", "-y", "-i", str(src), "-vn"]
    if max_minutes:
        cmd += ["-t", str(int(max_minutes * 60))]
    cmd += ["-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)]
    core._run(cmd)
    audio, _ = sf.read(str(dst), dtype="float32")
    dst.unlink(missing_ok=True)
    return audio


def speech_regions(audio, log: Log) -> list[tuple[float, float]]:
    import torch
    from silero_vad import get_speech_timestamps
    ts = get_speech_timestamps(torch.from_numpy(audio), _vad(log),
                               sampling_rate=SR, return_seconds=True)
    return [(float(t["start"]), float(t["end"])) for t in ts
            if t["end"] - t["start"] >= MIN_REGION]


def slice_windows(regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Cut speech regions into overlapping fingerprint slices."""
    wins = []
    for start, end in regions:
        if end - start <= WIN:
            wins.append((start, end))
            continue
        t = start
        while t + WIN <= end + 1e-6:
            wins.append((t, t + WIN))
            t += HOP
        if wins[-1][1] < end - HOP / 2:  # cover the tail
            wins.append((end - WIN, end))
    return wins


def fingerprints(audio, wins, log: Log, batch: int = 32):
    """One unit-length voice fingerprint per slice."""
    import numpy as np
    import torch
    enc = _encoder(log)
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    out = []
    for i in range(0, len(wins), batch):
        chunk = wins[i:i + batch]
        pieces = [audio[int(s * SR):int(e * SR)] for s, e in chunk]
        longest = max(len(p) for p in pieces)
        padded = np.zeros((len(pieces), longest), dtype="float32")
        for j, p in enumerate(pieces):
            padded[j, :len(p)] = p
        lens = torch.tensor([len(p) / longest for p in pieces])
        with torch.no_grad():
            emb = enc.encode_batch(torch.from_numpy(padded), lens).squeeze(1).numpy()
        out.append(emb)
        if len(wins) > 400 and (i // batch) % 25 == 0:
            log(f"  fingerprints {min(i + batch, len(wins))}/{len(wins)}")
    emb = np.concatenate(out) if out else np.zeros((0, 192), dtype="float32")
    norms = np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    return emb / norms


def group_voices(emb, threshold: float = GROUP_THRESHOLD):
    import numpy as np
    if len(emb) < 2:
        return np.zeros(len(emb), dtype=int)
    from sklearn.cluster import AgglomerativeClustering
    model = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                    distance_threshold=threshold)
    return model.fit_predict(emb)


def sample_print(sample: Path, tmp: Path, log: Log):
    """Average fingerprint of a voice sample file."""
    import numpy as np
    audio = load_16k(sample, tmp, max_minutes=5)
    regions = speech_regions(audio, log) or [(0.0, len(audio) / SR)]
    emb = fingerprints(audio, slice_windows(regions), log)
    if not len(emb):
        raise RuntimeError(f"No speech found in the sample {sample.name}")
    v = emb.mean(0)
    return v / (np.linalg.norm(v) + 1e-9)


# ---- core: who is talking when -----------------------------------------------
def _labelled_pieces(wins, labels, regions):
    """Give each window's middle part its label, clipped to its speech region."""
    pieces = []
    for (s, e), lab in zip(wins, labels):
        mid = (s + e) / 2
        half = min(HOP, e - s) / 2
        a, b = mid - half, mid + half
        for rs, re_ in regions:
            if rs <= mid <= re_:
                a, b = max(a, rs), min(b, re_)
                break
        if b > a:
            pieces.append((a, b, int(lab)))
    return pieces


def _merge(pieces, total: float) -> list[tuple[float, float]]:
    segs: list[list[float]] = []
    for a, b in sorted(pieces):
        if segs and a - segs[-1][1] <= JOIN_GAP:
            segs[-1][1] = max(segs[-1][1], b)
        else:
            segs.append([a, b])
    out = []
    for a, b in segs:
        if b - a >= MIN_SEG:
            out.append((max(0.0, a - PAD), min(total, b + PAD)))
    return out


def analyse(audio, log: Log, ref=None, threshold: float = GROUP_THRESHOLD) -> Result:
    import numpy as np
    total = len(audio) / SR
    regions = speech_regions(audio, log)
    speech = sum(e - s for s, e in regions)
    if speech < 3:
        return Result([], 0, 0.0, speech, "-", "low", "Almost no speech found")
    wins = slice_windows(regions)
    log(f"  {speech / 60:.1f} min of speech, {len(wins)} slices; fingerprinting...")
    emb = fingerprints(audio, wins, log)
    labels = group_voices(emb, threshold)
    pieces = _labelled_pieces(wins, labels, regions)

    talk: dict[int, float] = {}
    for a, b, lab in pieces:
        talk[lab] = talk.get(lab, 0.0) + (b - a)
    heard = sum(talk.values()) or 1.0
    real = {k: v for k, v in talk.items() if v / heard >= MIN_GROUP_SHARE}
    voices = len(real) or 1

    note = ""
    if ref is not None:
        sims = {}
        for lab in real:
            c = emb[labels == lab].mean(0)
            sims[lab] = float(np.dot(c / (np.linalg.norm(c) + 1e-9), ref))
        target = max(sims, key=sims.get)
        best = sims[target]
        picked = "voice sample"
        others = sorted(sims.values(), reverse=True)
        gap = best - (others[1] if len(others) > 1 else 0.0)
        if best >= 0.6 and gap >= 0.15:
            conf = "high"
        elif best >= SAMPLE_MATCH:
            conf = "medium"
        else:
            conf = "low"
            note = f"Sample only matched {best:.2f}; check by ear"
    else:
        target = max(real, key=real.get)
        picked = "most talking"
        share = real[target] / heard
        conf = "high" if share >= 0.6 else "medium" if share >= 0.4 else "low"
        if voices > 1:
            note = f"Wanted voice is {share:.0%} of the talking"
        if conf == "low":
            note += "; no clear main voice, add a voice sample"

    segs = _merge([(a, b) for a, b, lab in pieces if lab == target], total)
    kept = sum(b - a for a, b in segs)
    return Result(segs, voices, kept, speech, picked, conf, note.strip("; "))


def find_speaker(src: Path, log: Log, sample: Path | None = None,
                 max_minutes: float | None = DEFAULT_MAX_MINUTES,
                 threshold: float = GROUP_THRESHOLD) -> Result:
    with tempfile.TemporaryDirectory(prefix="clipvox_spk_") as tmp:
        tmp = Path(tmp)
        ref = sample_print(sample, tmp, log) if sample else None
        audio = load_16k(Path(src), tmp, max_minutes)
        return analyse(audio, log, ref=ref, threshold=threshold)


# ---- formatting --------------------------------------------------------------
def fmt_time(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_ranges(segs) -> str:
    return ", ".join(f"{fmt_time(a)}-{fmt_time(b)}" for a, b in segs)


def jump_link(url: str, sec: float) -> str:
    base = re.sub(r"[&?]t=\d+s?", "", url)
    return f"{base}{'&' if '?' in base else '?'}t={int(sec)}s"


# ---- cutting the wanted voice out of a file ----------------------------------
def keep_segments(src_wav: Path, dst_wav: Path, segs, gap: float = 0.25) -> float:
    """Write only the given time ranges of src_wav to dst_wav. Returns seconds kept."""
    import numpy as np
    import soundfile as sf
    info = sf.info(str(src_wav))
    rate, ch = info.samplerate, info.channels
    silence = np.zeros((int(gap * rate), ch), dtype="float32")
    kept = 0.0
    with sf.SoundFile(str(dst_wav), "w", rate, ch, subtype="PCM_16") as out:
        for a, b in segs:
            data, _ = sf.read(str(src_wav), start=int(a * rate), stop=int(b * rate),
                              dtype="float32", always_2d=True)
            if not len(data):
                continue
            out.write(data)
            out.write(silence)
            kept += len(data) / rate
    return kept


# ---- batch from the sheet ----------------------------------------------------
def find_sample(samples_dir: Path | None, character: str, show: str) -> Path | None:
    if not samples_dir or not samples_dir.is_dir():
        return None
    wanted = {core.safe_name(f"{show} {character}").lower(),
              core.safe_name(character).lower()}
    for f in sorted(samples_dir.iterdir()):
        if f.suffix.lower() in core.AUDIO_EXTS and f.stem.lower() in wanted:
            return f
    return None


def _done_keys(out_csv: Path) -> set[tuple[str, str]]:
    """Rows already finished. Rows that failed are removed so they get retried."""
    if not out_csv.exists():
        return set()
    with open(out_csv, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    good = [r for r in rows if r.get("Confidence") != "error"]
    if len(good) != len(rows):
        with open(out_csv, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=OUT_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(good)
    return {(r.get("Character", ""), r.get("URL", "")) for r in good}


def run_batch(csv_in: Path, out_csv: Path, log: Log, samples_dir: Path | None = None,
              max_minutes: float | None = DEFAULT_MAX_MINUTES,
              status: str | None = "Needs trimming", limit: int | None = None,
              stop: Callable[[], bool] = lambda: False) -> int:
    with open(csv_in, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or "URL" not in rows[0]:
        raise ValueError("That CSV has no URL column. Download it from the sheet's "
                         "Needs Trimming page.")
    todo = []
    for r in rows:
        url = (r.get("URL") or "").strip()
        if status and (r.get("Status") or status).strip().lower() != status.lower():
            continue
        if "youtube.com/results" in url or not core.is_url(url):
            continue  # search links: nothing to analyse yet
        todo.append(r)
    done = _done_keys(out_csv)
    todo = [r for r in todo if (r.get("Character", ""), r["URL"].strip()) not in done]
    if limit:
        todo = todo[:limit]
    log(f"{len(todo)} video(s) to check ({len(done)} already done in {out_csv.name}).")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out_csv.exists()
    count = 0
    with open(out_csv, "a", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        if new_file:
            w.writeheader()
        for i, r in enumerate(todo, 1):
            if stop():
                log("Stopped. Run it again to pick up where it left off.")
                break
            char, show, url = r.get("Character", ""), r.get("Show", ""), r["URL"].strip()
            log(f"[{i}/{len(todo)}] {char} ({show})")
            row = {"Character": char, "Show": show, "URL": url}
            try:
                sample = find_sample(samples_dir, char, show)
                if sample:
                    log(f"  using voice sample {sample.name}")
                with tempfile.TemporaryDirectory(prefix="clipvox_dl_") as tmp:
                    raw, _ = core.download_audio(url, Path(tmp), log)
                    res = find_speaker(raw, log, sample=sample, max_minutes=max_minutes)
                row.update({
                    "Timestamps": fmt_ranges(res.segments),
                    "Wanted speech": fmt_time(res.target_seconds),
                    "Voices found": res.voices,
                    "Picked by": res.picked_by,
                    "Confidence": res.confidence,
                    "Jump to first": jump_link(url, res.segments[0][0]) if res.segments else "",
                    "Note": "; ".join(x for x in (
                        res.note, f"first {max_minutes:g} min checked" if max_minutes else "")
                        if x),
                })
                log(f"  {fmt_time(res.target_seconds)} of wanted speech, "
                    f"{res.voices} voice(s), confidence {res.confidence}")
            except Exception as exc:
                row.update({"Confidence": "error", "Note": str(exc)[:300]})
                log(f"  ERROR: {exc}")
            w.writerow(row)
            fh.flush()
            count += 1
    log(f"Done. {count} row(s) written to {out_csv}")
    return count
