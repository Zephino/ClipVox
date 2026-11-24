# ClipVox

Turn YouTube videos or audio files into clean voice clips for training an AI voice, in the exact format **TikTrigz** uses:

**WAV · 16-bit PCM · mono · 22,050 Hz** · up to 20 clips · each ≤ 12 MB and under 5 minutes

- **PC tool (Windows):** paste YouTube links → downloads → removes music, crowd and background noise → saves ready-to-use clips.
- **Web page:** convert audio you've already cleaned, right in your browser. Nothing gets uploaded.
  The page lives in [`docs/`](docs/index.html) and is published with GitHub Pages.

## Install (Windows)

1. Install **Python 3.12** from <https://www.python.org/downloads/>. On the first screen, tick **"Add python.exe to PATH"**.
2. Download this repo: **Code → Download ZIP**, then right-click the zip → **Extract All…**
3. Double-click **`install.bat`**. The first install downloads about 1 GB, so give it a few minutes.
4. Double-click **`run.bat`** to open ClipVox.

## Use it

1. Paste YouTube links (one per line), or click **Add files…** to use audio files you already have.
2. Give the voice a name, e.g. `macho_man`.
3. Click **Make clips**. Clips go into the `output` folder, named like `macho_man_01.wav`.

The first time you use music removal, ClipVox downloads the voice-separation model (~80 MB).
It runs on the CPU and takes a few minutes for every 10 minutes of audio.

### Find when the wanted person is talking

Interviews have a host talking too, and cartoon compilations have other characters.
ClipVox can find the wanted voice for you.

**For a whole list (from the sheet):**

1. On the sheet, open the **Needs Trimming** page and download it as a CSV.
2. In ClipVox, click **Find timestamps (sheet CSV)...** and pick that file.
3. It checks each video (the first 20 minutes) and writes `output\timestamps.csv`:
   the time ranges where the wanted voice talks, how much was found, how sure it is,
   and a link that jumps to the first good spot. Click **Stop** any time; running it
   again picks up where it left off.

It picks the voice that talks the most, which is the guest in an interview. When that's
wrong (a compilation where someone else talks more), add a **voice sample**: a 5-30 second
clip of just that voice, saved in the `samples` folder and named after the character, like
`samples\Peter_Griffin.wav`. Rows marked confidence **low** are the ones to check by ear.

**For clips you're making now:** tick **Keep only the wanted voice**, and optionally click
**Voice sample...** to pick a clip of the right voice.

The first run downloads two small models (about 85 MB). It runs on the CPU; expect a
minute or two per 20 minutes of video.

### Command line

Open **Command Prompt** in the ClipVox folder, then run:

```
.venv\Scripts\python.exe clipvox.py --cli "https://www.youtube.com/watch?v=VIDEO_ID" -n macho_man
```

| Option | What it does |
|---|---|
| `-o FOLDER` | Where to save clips (default `output`) |
| `-n NAME` | Name for the clips |
| `--keep-music` | Skip music/noise removal (faster) |
| `--keep-silence` | Don't shorten long pauses |
| `--no-normalize` | Don't even out the volume |
| `--clip-seconds N` | Clip length (default 240) |
| `--only-speaker` | Keep only the wanted voice |
| `--sample FILE` | Voice sample of the wanted person |

Find timestamps for a sheet CSV:

```
.venv\Scripts\python.exe clipvox.py --timestamps "C:\Users\YOU\Downloads\Needs Trimming.csv"
```

| Option | What it does |
|---|---|
| `-o FILE` | Where to save (default `output\timestamps.csv`) |
| `--samples FOLDER` | Folder of voice samples (default `samples`) |
| `--max-minutes N` | Only check the first N minutes of each video (default 20, `0` = all) |
| `--limit N` | Only do N videos (good for a test run) |
| `--any-status` | Check every row with a video link, not just Needs trimming |

### If YouTube downloads stop working

YouTube changes things often. Double-click **`update.bat`** to update the downloader.

## Turn on the web page (GitHub Pages)

On GitHub, open the repo's **Settings → Pages**. Under **Build and deployment**, set **Source** to *Deploy from a branch*, choose **Branch: `main`**, and set the folder to **`/docs`**. Click **Save**.
After a minute the page is live at `https://zephino.github.io/<repo-name>/`.

## Tips for a good voice

- Use interviews and sit-down promos. Skip entrance music, crowds, and anyone else talking.
- 5–15 minutes of clean speech is plenty. Listen to the clips and delete any bad ones.

## Use it responsibly

ClipVox is for fun and parody. Clone your own voice or voices you have permission to use, label AI voices as AI
(TikTok requires it for realistic AI content), and don't use a cloned voice to fool people or make money.
Downloading from YouTube may be against YouTube's Terms of Service, so that part is your responsibility.

## Project files

`VERSION` · [`CHANGELOG.md`](CHANGELOG.md) · [`SECURITY.md`](SECURITY.md) · [`LICENSE`](LICENSE) (MIT)
