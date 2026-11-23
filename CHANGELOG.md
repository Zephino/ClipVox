# Changelog

All notable changes to ClipVox are listed here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/).

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
