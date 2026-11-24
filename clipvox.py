"""ClipVox - turn YouTube videos or audio files into TikTrigz-ready voice clips.

Double-click run.bat to open the window, or use the command line:
    python clipvox.py --cli "https://youtu.be/..." -o output
    python clipvox.py --timestamps "Needs Trimming.csv"
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
from pathlib import Path

import clipvox_core as core

# Windows consoles use a legacy code page; video titles with emoji would crash print().
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

APP_DIR = Path(__file__).resolve().parent
VERSION = (APP_DIR / "VERSION").read_text().strip() if (APP_DIR / "VERSION").exists() else "dev"


def run_cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="clipvox", description="Make TikTrigz voice clips.")
    p.add_argument("--cli", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("sources", nargs="+", help="YouTube links and/or audio files")
    p.add_argument("-o", "--out", default=str(APP_DIR / "output"), help="output folder")
    p.add_argument("-n", "--name", help="name for the clips (e.g. macho_man)")
    p.add_argument("--keep-music", action="store_true", help="skip music/noise removal")
    p.add_argument("--keep-silence", action="store_true", help="don't shorten long pauses")
    p.add_argument("--no-normalize", action="store_true", help="don't even out volume")
    p.add_argument("--clip-seconds", type=int, default=core.CLIP_SECONDS)
    p.add_argument("--only-speaker", action="store_true",
                   help="keep only the wanted voice (cuts out interviewers)")
    p.add_argument("--sample", help="voice sample file of the wanted person (optional)")
    a = p.parse_args(argv)
    opts = core.Options(remove_music=not a.keep_music, trim_silence=not a.keep_silence,
                        normalize=not a.no_normalize, clip_seconds=a.clip_seconds,
                        speaker_only=a.only_speaker or bool(a.sample),
                        speaker_sample=a.sample)
    clips = core.process(a.sources, Path(a.out), opts, print, name=a.name)
    return 0 if clips else 1


def run_timestamps(argv: list[str]) -> int:
    import clipvox_speaker as spk
    p = argparse.ArgumentParser(prog="clipvox --timestamps",
                                description="Find when the wanted person talks in each video.")
    p.add_argument("--timestamps", metavar="CSV", required=True,
                   help="CSV downloaded from the sheet's Needs Trimming page")
    p.add_argument("-o", "--out", default=str(APP_DIR / "output" / "timestamps.csv"))
    p.add_argument("--samples", default=str(APP_DIR / "samples"),
                   help="folder of voice samples named like Peter_Griffin.wav")
    p.add_argument("--max-minutes", type=float, default=spk.DEFAULT_MAX_MINUTES,
                   help="only check the first N minutes of each video (0 = all)")
    p.add_argument("--limit", type=int, help="only do this many videos")
    p.add_argument("--any-status", action="store_true",
                   help="check every row with a video link, not just Needs trimming")
    a = p.parse_args(argv)
    spk.run_batch(Path(a.timestamps), Path(a.out), print, samples_dir=Path(a.samples),
                  max_minutes=a.max_minutes or None, limit=a.limit,
                  status=None if a.any_status else "Needs trimming")
    return 0


def run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title(f"ClipVox {VERSION} - TikTrigz voice clips")
    root.geometry("820x680")
    root.minsize(640, 520)
    pad = {"padx": 10, "pady": 4}

    ttk.Label(root, text="YouTube links or audio files (one per line):",
              font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad)
    src_box = scrolledtext.ScrolledText(root, height=6, font=("Consolas", 10))
    src_box.pack(fill="x", **pad)

    def add_files():
        files = filedialog.askopenfilenames(
            title="Pick audio or video files",
            filetypes=[("Audio/Video", " ".join("*" + e for e in sorted(core.AUDIO_EXTS))),
                       ("All files", "*.*")])
        for f in files:
            src_box.insert("end", f + "\n")

    row = ttk.Frame(root)
    row.pack(fill="x", **pad)
    ttk.Button(row, text="Add files...", command=add_files).pack(side="left")
    ttk.Button(row, text="Clear", command=lambda: src_box.delete("1.0", "end")).pack(side="left", padx=6)

    form = ttk.Frame(root)
    form.pack(fill="x", **pad)
    ttk.Label(form, text="Voice name:").grid(row=0, column=0, sticky="w")
    name_var = tk.StringVar(value="")
    ttk.Entry(form, textvariable=name_var, width=30).grid(row=0, column=1, sticky="w", padx=6)
    ttk.Label(form, text="(optional, e.g. macho_man)").grid(row=0, column=2, sticky="w")

    ttk.Label(form, text="Save to:").grid(row=1, column=0, sticky="w", pady=4)
    out_var = tk.StringVar(value=str(APP_DIR / "output"))
    ttk.Entry(form, textvariable=out_var, width=60).grid(row=1, column=1, columnspan=2, sticky="we", padx=6)

    def pick_out():
        d = filedialog.askdirectory(initialdir=out_var.get())
        if d:
            out_var.set(d)

    ttk.Button(form, text="Browse...", command=pick_out).grid(row=1, column=3)
    form.columnconfigure(2, weight=1)

    opts_frame = ttk.LabelFrame(root, text="Clean-up")
    opts_frame.pack(fill="x", **pad)
    music_var = tk.BooleanVar(value=True)
    silence_var = tk.BooleanVar(value=True)
    norm_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(opts_frame, text="Remove music, crowd and background noise (slower)",
                    variable=music_var).pack(anchor="w", padx=8)
    ttk.Checkbutton(opts_frame, text="Shorten long pauses", variable=silence_var).pack(anchor="w", padx=8)
    ttk.Checkbutton(opts_frame, text="Even out the volume", variable=norm_var).pack(anchor="w", padx=8)
    speaker_var = tk.BooleanVar(value=False)
    sample_var = tk.StringVar(value="")
    spk_row = ttk.Frame(opts_frame)
    spk_row.pack(fill="x", padx=8)
    ttk.Checkbutton(spk_row, text="Keep only the wanted voice (cuts out interviewers)",
                    variable=speaker_var).pack(side="left")

    def pick_sample():
        f = filedialog.askopenfilename(
            title="Pick a short clip of the wanted voice (5-30 seconds)",
            filetypes=[("Audio/Video", " ".join("*" + e for e in sorted(core.AUDIO_EXTS))),
                       ("All files", "*.*")])
        if f:
            sample_var.set(f)
            speaker_var.set(True)

    ttk.Button(spk_row, text="Voice sample...", command=pick_sample).pack(side="left", padx=6)
    ttk.Label(spk_row, textvariable=sample_var, foreground="#555").pack(side="left")

    ttk.Label(root, text="Output: WAV, 16-bit PCM, mono, 22,050 Hz - up to 20 clips, "
                         "each under 12 MB and 5 minutes.",
              foreground="#555").pack(anchor="w", **pad)

    log_box = scrolledtext.ScrolledText(root, height=12, font=("Consolas", 9), state="disabled")
    log_box.pack(fill="both", expand=True, **pad)
    bar = ttk.Progressbar(root, mode="indeterminate")
    bar.pack(fill="x", **pad)

    msgs: "queue.Queue[str]" = queue.Queue()

    def log(text: str) -> None:
        msgs.put(text)

    def pump():
        while not msgs.empty():
            text = msgs.get()
            log_box.configure(state="normal")
            log_box.insert("end", text + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")
        root.after(150, pump)

    btns = ttk.Frame(root)
    btns.pack(fill="x", **pad)
    start_btn = ttk.Button(btns, text="Make clips")
    start_btn.pack(side="right")

    def open_out():
        out = Path(out_var.get())
        out.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(out)  # noqa: S606 - opens the user's own folder

    ttk.Button(btns, text="Open output folder", command=open_out).pack(side="right", padx=6)

    stop_flag = threading.Event()
    ts_btn = ttk.Button(btns, text="Find timestamps (sheet CSV)...")
    ts_btn.pack(side="left")
    stop_btn = ttk.Button(btns, text="Stop", state="disabled", command=stop_flag.set)
    stop_btn.pack(side="left", padx=6)

    def ts_worker(csv_path: Path, out_csv: Path):
        import clipvox_speaker as spk
        try:
            spk.run_batch(csv_path, out_csv, log, samples_dir=APP_DIR / "samples",
                          stop=stop_flag.is_set)
            log(f"Timestamps saved to {out_csv}. Send that file to Claude to fill the sheet.")
        except Exception as exc:
            log(f"ERROR: {exc}")
        finally:
            root.after(0, lambda: (bar.stop(), ts_btn.configure(state="normal"),
                                   start_btn.configure(state="normal"),
                                   stop_btn.configure(state="disabled")))

    def start_ts():
        f = filedialog.askopenfilename(title="Pick the CSV from the sheet's Needs Trimming page",
                                       filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not f:
            return
        out_csv = Path(out_var.get()) / "timestamps.csv"
        stop_flag.clear()
        ts_btn.configure(state="disabled")
        start_btn.configure(state="disabled")
        stop_btn.configure(state="normal")
        bar.start(12)
        threading.Thread(target=ts_worker, daemon=True, args=(Path(f), out_csv)).start()

    ts_btn.configure(command=start_ts)

    def worker(sources, out, opts, name):
        try:
            clips = core.process(sources, out, opts, log, name=name)
            log("" if clips else "No clips were made - see the messages above.")
        except Exception as exc:
            log(f"ERROR: {exc}")
        finally:
            root.after(0, lambda: (bar.stop(), start_btn.configure(state="normal")))

    def start():
        sources = [s for s in src_box.get("1.0", "end").splitlines() if s.strip()]
        if not sources:
            messagebox.showinfo("ClipVox", "Paste a YouTube link or add a file first.")
            return
        opts = core.Options(remove_music=music_var.get(), trim_silence=silence_var.get(),
                            normalize=norm_var.get(), speaker_only=speaker_var.get(),
                            speaker_sample=sample_var.get() or None)
        start_btn.configure(state="disabled")
        bar.start(12)
        threading.Thread(target=worker, daemon=True,
                         args=(sources, Path(out_var.get()), opts,
                               name_var.get().strip() or None)).start()

    start_btn.configure(command=start)
    pump()
    log("Ready. Use clean, single-speaker speech: interviews and promos, "
        "not clips with lots of music or crowd noise.")
    root.mainloop()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--timestamps":
        sys.exit(run_timestamps(args))
    if args and (args[0] == "--cli" or not args[0].startswith("-")):
        sys.exit(run_cli(args))
    run_gui()
