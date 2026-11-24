# Security Policy

## Supported versions
Only the latest release gets fixes.

## Reporting a problem
Open a private report through GitHub's **Security → Report a vulnerability** tab on this repo.
Please don't post security problems in public issues.

## How ClipVox handles your data
- **Browser converter:** runs entirely in your browser. Files are never uploaded anywhere.
- **PC tool:** everything runs on your own computer. The only network traffic is:
  - downloading the links *you* paste (through yt-dlp),
  - a one-time download of the Demucs voice-separation model from Meta's server,
  - a one-time download of the SpeechBrain voice-fingerprint model from Hugging Face
    (saved in `models\ecapa`); the speech detector ships inside its Python package,
  - installing Python packages from PyPI when you run `install.bat`.
- ClipVox stores no accounts, keys or passwords, and has no telemetry.
- Only `http://` and `https://` links are accepted. Local paths must be real audio/video files.
- Temporary files are written to a private temp folder and deleted when the job ends.
- Output never overwrites existing files.
- The speaker finder only reads the CSV you pick and writes `timestamps.csv`; voice
  fingerprints stay in memory and are never saved or sent anywhere.

## Keeping it safe
- Run `update.bat` now and then to keep yt-dlp current.
- Only paste links you trust. Only run `.bat` files you downloaded from this repo.
