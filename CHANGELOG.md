# Changelog

All notable changes to ClipVox are listed here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/).

## [1.1.1] - 2026-11-23
### Fixed
- Crash ("max() iterable argument is empty") on videos with many voices where no single voice
  passed the minimum share.

### Changed
- Voice grouping is looser (`GROUP_THRESHOLD` 0.55 to 0.75). Short 1.5-second slices of one
  person are often 0.6 to 0.9 apart, so 0.55 split one person into hundreds of voices.

## [1.1.0] - 2026-11-23
### Added
- Speaker finder (`clipvox_speaker.py`): works out when the wanted person is talking.
  Finds speech (Silero VAD), takes a voice fingerprint of each 1.5-second slice
  (SpeechBrain ECAPA), groups slices by voice, and picks the voice that talks the most,
  or the one that matches a voice sample if you give one.
- **Find timestamps (sheet CSV)** button and `--timestamps` command: reads the CSV from the
  sheet's Needs Trimming page and writes `output/timestamps.csv` with time ranges, how much
  wanted speech was found, how many voices, confidence and a jump-to link. Saves after every
  video, skips search links, and picks up where it left off (failed videos are retried).
- Voice samples: put a short clip in the `samples` folder named like `Peter_Griffin.wav`
  or `Family_Guy_Peter_Griffin.wav` and it is used for that row automatically.
- **Keep only the wanted voice** option (and `--only-speaker` / `--sample`) when making clips:
  cuts out interviewers and other voices before clean-up.

### Changed
- Install now also adds SpeechBrain, Silero VAD and scikit-learn (CPU only).

## [1.0.0] - 2026-11-23
### Added
- PC tool (`clipvox.py`) with a window and a command-line mode.
- Downloads audio from YouTube links (yt-dlp) or takes local audio/video files.
- Music, crowd and background-noise removal with Demucs (`htdemucs`, runs on CPU).
- Clean-up: 70 Hz high-pass, shortening long pauses, volume leveling.
- Output in the TikTrigz voice format: WAV, 16-bit PCM, mono, 22,050 Hz,
  split into 4-minute clips (~10.6 MB), max 20 clips, never overwrites existing files.
- Format check on every clip it saves.
- `install.bat`, `run.bat`, `update.bat` for Windows.
- GitHub Pages site (`docs/`) with an in-browser converter and ZIP download.
- Mobile-friendly page: full-width buttons, large tap targets, stacked clip players,
  "tap to pick" file chooser on phones.
