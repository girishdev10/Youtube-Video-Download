from flask import Flask, request, jsonify, send_file, after_this_request
from pytubefix import YouTube

import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import traceback


app = Flask(__name__)


# =============================================================================
# CORS
# =============================================================================

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response


# =============================================================================
# CONFIGURATION
# =============================================================================

PORT = 50000

WORK_DIR = tempfile.mkdtemp(prefix="ytdl_")

progress_store = {}

# Prevent multiple simultaneous downloads from interfering with each other.
download_lock = threading.Lock()


# =============================================================================
# SERVE index.html
# =============================================================================

@app.route("/")
def index():

    here = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(here, "index.html")

    if not os.path.exists(html_path):
        return "index.html not found in working directory.", 404

    return send_file(html_path)


# =============================================================================
# FILENAME
# =============================================================================

def safe_filename(name: str) -> str:

    if not name:
        return "video"

    invalid_chars = '<>:"/\\|?*'

    for ch in invalid_chars:
        name = name.replace(ch, "_")

    # Remove control characters.
    name = "".join(
        ch if ord(ch) >= 32 else "_"
        for ch in name
    )

    name = name.strip().strip(".")

    if not name:
        name = "video"

    # Avoid excessively long filenames.
    return name[:180]


# =============================================================================
# FILE SIZE
# =============================================================================

def format_size(size) -> str:

    try:

        if size is None:
            return "Unknown"

        size = int(size)

        if size >= 1024 ** 3:
            return f"{size / (1024 ** 3):.2f} GB"

        return f"{size / (1024 ** 2):.2f} MB"

    except Exception:
        return "Unknown"


# =============================================================================
# PROGRESS CALLBACK
# =============================================================================

def make_progress_cb(session_id: str, stage: str):

    def callback(stream, chunk, bytes_remaining):

        try:

            total = getattr(stream, "filesize", None)

            if not total:
                return

            done = total - bytes_remaining

            percent = round(
                done / total * 100,
                1
            )

            progress_store[session_id] = {
                "stage": stage,
                "percent": percent,
                "done": done,
                "total": total
            }

        except Exception:
            pass

    return callback


# =============================================================================
# CREATE YOUTUBE OBJECT
# =============================================================================

def create_youtube(
    url,
    session_id=None,
    stage="loading"
):

    callback = None

    if session_id:
        callback = make_progress_cb(
            session_id,
            stage
        )

    """
    WEB is intentionally used.

    Do not force use_po_token=True here.

    pytubefix handles the PO-token generation mechanism for supported
    clients internally.
    """

    return YouTube(
        url,
        client="WEB",
        on_progress_callback=callback
    )


# =============================================================================
# STREAM HELPERS
# =============================================================================

def is_sabr(stream):

    try:
        return bool(stream.is_sabr)

    except Exception:
        return False


def get_video_streams(yt):

    streams = (
        yt.streams
        .filter(
            adaptive=True,
            only_video=True
        )
        .order_by("resolution")
        .desc()
    )

    return list(streams)


def get_audio_streams(yt):

    streams = (
        yt.streams
        .filter(
            adaptive=True,
            only_audio=True
        )
        .order_by("abr")
        .desc()
    )

    return list(streams)


def choose_best_audio(yt, video_mime):

    all_audio = get_audio_streams(yt)

    if not all_audio:
        return None

    # Prefer AAC / MP4 audio for MP4 video.
    if "mp4" in video_mime.lower():

        mp4_audio = [
            s for s in all_audio
            if (s.mime_type or "").lower() == "audio/mp4"
        ]

        if mp4_audio:
            return mp4_audio[0]

    # Otherwise prefer WebM audio.
    else:

        webm_audio = [
            s for s in all_audio
            if (s.mime_type or "").lower() == "audio/webm"
        ]

        if webm_audio:
            return webm_audio[0]

    # Final fallback.
    return all_audio[0]


# =============================================================================
# ERROR RESPONSE
# =============================================================================

def pytube_error_response(error):

    error_text = str(error)
    error_type = type(error).__name__

    print()
    print("=" * 80)
    print("PYTUBEFIX ERROR")
    print("=" * 80)
    print("TYPE:", error_type)
    print("ERROR:", error_text)
    print("=" * 80)
    print()

    lower = error_text.lower()

    if (
        "bot" in lower
        or "po_token" in lower
        or "potoken" in lower
        or "sabr" in lower
        or "maximum reload attempts" in lower
    ):

        message = (
            "YouTube rejected the stream request because the required "
            "stream protection / PO token was not accepted by YouTube. "
            "This is a pytubefix/YouTube stream-protection issue, not FFmpeg."
        )

    elif "403" in lower:

        message = (
            "YouTube returned HTTP 403 Forbidden while accessing the stream."
        )

    elif "private" in lower:

        message = "This video is private."

    elif "unavailable" in lower:

        message = "This video is unavailable."

    elif "age" in lower:

        message = "This video requires age verification."

    else:

        message = error_text

    return jsonify({
        "error": message,
        "exception": error_type,
        "details": error_text
    }), 500


# =============================================================================
# ANALYSE
# =============================================================================

@app.route(
    "/analyse",
    methods=["POST", "OPTIONS"]
)
def analyse():

    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(
        force=True,
        silent=True
    ) or {}

    url = (data.get("url") or "").strip()

    if not url:

        return jsonify({
            "error": "URL parameter missing"
        }), 400

    try:

        print()
        print("=" * 80)
        print("ANALYSING VIDEO")
        print(url)
        print("=" * 80)

        yt = create_youtube(url)

        # Force metadata retrieval.
        title = yt.title

        print("TITLE:", title)
        print("AUTHOR:", yt.author)
        print("LENGTH:", yt.length)

        # Retrieve streams.
        video_streams = get_video_streams(yt)

        streams_list = []

        seen = set()

        for stream in video_streams:

            resolution = stream.resolution or "?"

            if resolution in seen:
                continue

            seen.add(resolution)

            streams_list.append({

                "itag": stream.itag,

                "resolution": resolution,

                "mime_type": stream.mime_type,

                "size": format_size(
                    getattr(
                        stream,
                        "filesize",
                        None
                    )
                ),

                "fps": getattr(
                    stream,
                    "fps",
                    None
                )
            })

        print(
            "VIDEO STREAMS FOUND:",
            len(streams_list)
        )

        return jsonify({

            "title": title,

            "thumbnail": yt.thumbnail_url,

            "views": yt.views,

            "author": yt.author,

            "length": yt.length,

            "streams": streams_list

        })

    except Exception as error:

        traceback.print_exc()

        return pytube_error_response(error)


# =============================================================================
# DOWNLOAD
# =============================================================================

@app.route(
    "/download",
    methods=["POST", "OPTIONS"]
)
def download():

    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(
        force=True,
        silent=True
    ) or {}

    url = (data.get("url") or "").strip()

    itag = data.get("itag")

    session_id = (
        data.get("session_id")
        or str(uuid.uuid4())
    )

    if not url or not itag:

        return jsonify({
            "error": "Missing selection arguments"
        }), 400

    # FFmpeg check.
    ffmpeg_path = shutil.which("ffmpeg")

    if ffmpeg_path is None:

        return jsonify({
            "error": (
                "FFmpeg binaries missing on host system. "
                "Install FFmpeg and make sure it is in PATH."
            )
        }), 500

    work = os.path.join(
        WORK_DIR,
        session_id
    )

    os.makedirs(
        work,
        exist_ok=True
    )

    try:

        progress_store[session_id] = {
            "stage": "loading",
            "percent": 0
        }

        print()
        print("=" * 80)
        print("STARTING DOWNLOAD")
        print("URL:", url)
        print("ITAG:", itag)
        print("SESSION:", session_id)
        print("=" * 80)

        # =====================================================================
        # CREATE ONE YouTube OBJECT
        # =====================================================================

        yt = create_youtube(
            url,
            session_id=session_id,
            stage="loading"
        )

        # =====================================================================
        # TITLE
        # =====================================================================

        title = safe_filename(
            yt.title
        )

        # =====================================================================
        # FIND SELECTED VIDEO STREAM
        # =====================================================================

        progress_store[session_id] = {
            "stage": "loading",
            "percent": 0
        }

        video_stream = yt.streams.get_by_itag(
            int(itag)
        )

        if video_stream is None:

            return jsonify({
                "error": (
                    "Selected video stream is no longer "
                    "available. Analyse the URL again."
                )
            }), 400

        video_mime = (
            video_stream.mime_type
            or "video/mp4"
        )

        print(
            "VIDEO:",
            video_stream.itag,
            video_mime,
            video_stream.resolution
        )

        # =====================================================================
        # SELECT AUDIO
        # =====================================================================

        audio_stream = choose_best_audio(
            yt,
            video_mime
        )

        if audio_stream is None:

            return jsonify({
                "error": "No companion audio stream available."
            }), 500

        print(
            "AUDIO:",
            audio_stream.itag,
            audio_stream.mime_type,
            audio_stream.abr
        )

        # =====================================================================
        # OUTPUT FORMAT
        # =====================================================================

        if "mp4" in video_mime.lower():

            output_ext = "mp4"

        else:

            output_ext = "mkv"

        # =====================================================================
        # VIDEO FILE EXTENSION
        # =====================================================================

        video_ext = (
            video_mime
            .split("/")
            [-1]
            .lower()
        )

        if video_ext not in (
            "mp4",
            "webm",
            "mkv"
        ):

            video_ext = "mp4"

        video_filename = (
            f"video.{video_ext}"
        )

        vfile = os.path.join(
            work,
            video_filename
        )

        # =====================================================================
        # DOWNLOAD VIDEO
        # =====================================================================

        progress_store[session_id] = {
            "stage": "video",
            "percent": 0
        }

        print("Downloading video...")

        video_stream.download(
            output_path=work,
            filename=video_filename
        )

        if not os.path.exists(vfile):

            raise RuntimeError(
                "Video download finished but "
                "the output file was not found."
            )

        print(
            "Video downloaded:",
            os.path.getsize(vfile),
            "bytes"
        )

        # =====================================================================
        # DOWNLOAD AUDIO
        # =====================================================================

        progress_store[session_id] = {
            "stage": "audio",
            "percent": 0
        }

        audio_stream2 = (
            yt.streams.get_by_itag(
                int(audio_stream.itag)
            )
        )

        if audio_stream2 is None:

            raise RuntimeError(
                "The selected audio stream became "
                "unavailable."
            )

        audio_mime = (
            audio_stream.mime_type
            or "audio/mp4"
        )

        audio_ext = (
            audio_mime
            .split("/")
            [-1]
            .lower()
        )

        if audio_ext == "mp4":

            audio_ext = "m4a"

        elif audio_ext not in (
            "m4a",
            "webm",
            "ogg"
        ):

            audio_ext = "m4a"

        audio_filename = (
            f"audio.{audio_ext}"
        )

        afile = os.path.join(
            work,
            audio_filename
        )

        print("Downloading audio...")

        audio_stream2.download(
            output_path=work,
            filename=audio_filename
        )

        if not os.path.exists(afile):

            raise RuntimeError(
                "Audio download finished but "
                "the output file was not found."
            )

        print(
            "Audio downloaded:",
            os.path.getsize(afile),
            "bytes"
        )

        # =====================================================================
        # MERGE
        # =====================================================================

        progress_store[session_id] = {
            "stage": "merging",
            "percent": 99
        }

        resolution = (
            video_stream.resolution
            or "video"
        )

        merged_name = (
            f"{title}_{resolution}.{output_ext}"
        )

        merged_file = os.path.join(
            work,
            merged_name
        )

        print("Merging with FFmpeg...")

        ffmpeg_command = [

            ffmpeg_path,

            "-hide_banner",

            "-loglevel",
            "error",

            "-i",
            vfile,

            "-i",
            afile,

            "-map",
            "0:v:0",

            "-map",
            "1:a:0",

            "-c:v",
            "copy",

            "-c:a",
            "copy",

            "-y",

            merged_file
        ]

        result = subprocess.run(
            ffmpeg_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:

            print()
            print("FFMPEG ERROR:")
            print(result.stderr)
            print()

            return jsonify({

                "error":
                    "FFmpeg failed while merging video and audio.",

                "details":
                    result.stderr[-5000:]
            }), 500

        if not os.path.exists(
            merged_file
        ):

            return jsonify({
                "error":
                    "FFmpeg finished but "
                    "the merged file was not created."
            }), 500

        # =====================================================================
        # COMPLETE
        # =====================================================================

        progress_store[session_id] = {
            "stage": "done",
            "percent": 100
        }

        print()
        print("=" * 80)
        print("DOWNLOAD COMPLETE")
        print("FILE:", merged_file)
        print("=" * 80)
        print()

        # =====================================================================
        # CLEANUP AFTER RESPONSE
        # =====================================================================

        @after_this_request
        def cleanup(response):

            def delete_files():

                # Keep the file alive while Flask sends it.
                time.sleep(60)

                try:

                    shutil.rmtree(
                        work,
                        ignore_errors=True
                    )

                except Exception:
                    pass

                progress_store.pop(
                    session_id,
                    None
                )

            threading.Thread(
                target=delete_files,
                daemon=True
            ).start()

            return response

        # =====================================================================
        # SEND FILE
        # =====================================================================

        return send_file(

            merged_file,

            as_attachment=True,

            download_name=merged_name,

            mimetype=(
                "video/mp4"
                if output_ext == "mp4"
                else "video/x-matroska"
            )
        )

    except Exception as error:

        traceback.print_exc()

        shutil.rmtree(
            work,
            ignore_errors=True
        )

        progress_store.pop(
            session_id,
            None
        )

        return pytube_error_response(
            error
        )


# =============================================================================
# PROGRESS
# =============================================================================

@app.route(
    "/progress/<session_id>",
    methods=["GET"]
)
def progress(session_id):

    info = progress_store.get(

        session_id,

        {
            "stage": "idle",
            "percent": 0
        }
    )

    return jsonify(info)


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.route(
    "/health",
    methods=["GET"]
)
def health():

    return jsonify({
        "status": "ok",
        "service": "YouTube Downloader",
        "ffmpeg": shutil.which("ffmpeg") is not None
    })


# =============================================================================
# CLEANUP
# =============================================================================

def cleanup_work_directory():

    try:

        if os.path.exists(WORK_DIR):

            shutil.rmtree(
                WORK_DIR,
                ignore_errors=True
            )

    except Exception:
        pass


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":

    try:

        print()
        print("=" * 80)
        print("YouTube Downloader Backend")
        print("=" * 80)
        print("Server: http://127.0.0.1:50000")
        print("Health: http://127.0.0.1:50000/health")
        print("FFmpeg:", shutil.which("ffmpeg"))
        print("Work directory:", WORK_DIR)
        print("=" * 80)
        print()

        app.run(
            debug=False,
            host="0.0.0.0",
            port=PORT,
            threaded=True
        )

    finally:

        cleanup_work_directory()