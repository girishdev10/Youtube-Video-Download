# YouTube Video Download

A simple YouTube downloader project with both command-line and GUI options.

## Repository Structure

- `CLI_Codes/`
  - `Youtube_Videio_Download_Mac.py` — macOS/Linux-friendly CLI downloader.
  - `Youtube_Videio_Download_Windows.py` — Windows-friendly CLI downloader.

- `GUI_Codes/`
  - `app.py` — Flask-based backend server for the web GUI.
  - `index.html` — front-end interface for analysing and downloading YouTube videos.

## Features

- Download adaptive video streams from YouTube.
- Automatically select a matching audio stream.
- Merge video and audio into a single output file using `ffmpeg`.
- Separate output directories for video, audio, and merged files.
- CLI versions for macOS/Linux and Windows.
- Web GUI version with request analysis and progress tracking.

## Requirements

- Python 3.8+
- `pytubefix` (or equivalent patched `pytube` package)
- `ffmpeg` installed and available in `PATH`
- For GUI: `Flask`

## Setup

1. Install Python dependencies:

```bash
pip install pytubefix flask
```

2. Install `ffmpeg`:

- macOS/Linux: `brew install ffmpeg` or use the system package manager.
- Windows: download from https://ffmpeg.org/ and add `ffmpeg` to your PATH.

## CLI Usage

### macOS / Linux

1. Open a terminal.
2. Run:

```bash
python CLI_Codes/Youtube_Videio_Download_Mac.py
```

3. Enter the YouTube URL when prompted.
4. Select the desired video `itag` from the displayed stream list.
5. The script downloads video and audio separately, then merges them.
6. Files are saved to the configured directories in `BASE_DIR`.

### Windows

1. Open Command Prompt or PowerShell.
2. Run:

```powershell
python CLI_Codes/Youtube_Videio_Download_Windows.py
```

3. Enter the YouTube URL when prompted.
4. Select the desired video `itag` from the displayed stream list.
5. The script downloads and merges the files.
6. Files are saved to the configured directories in `BASE_DIR`.

## GUI Usage

1. Open a terminal in `GUI_Codes/`.
2. Run the Flask server:

```bash
python GUI_Codes/app.py
```

3. Open a browser and navigate to:

```text
http://localhost:50000
```

4. Paste a YouTube URL into the interface and click `Analyse`.
5. Choose a stream and download the merged video.

## Notes

- The CLI scripts use fixed default output directories in `BASE_DIR`.
- Modify `BASE_DIR` in the script if you want a custom download location.
- The GUI server uses a temporary working directory and cleans up downloads after completion.

## Troubleshooting

- If `ffmpeg` is not found, install it and ensure it is in your system `PATH`.
- If `pytubefix` fails to import, install it with pip or replace it with a compatible `pytube` fork.
- If the script cannot create folders, run the terminal with appropriate permissions.

## License

This repository does not include a license file. Add a `LICENSE` if you want to make the usage terms explicit.
