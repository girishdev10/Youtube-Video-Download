from flask import Flask, request, jsonify, send_file, after_this_request
from pytubefix import YouTube
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

app = Flask(__name__)

# ─── CORS Handlers ────────────────────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        resp = app.make_default_options_response()
        resp.headers["Access-Control-Allow-Origin"]  = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

# ─── Serve index.html ─────────────────────────────────────────────────────────
@app.route("/")
def index():
    here = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(here, "index.html")
    if not os.path.exists(html_path):
        return "index.html not found in working directory.", 404
    return send_file(html_path)

WORK_DIR = tempfile.mkdtemp(prefix="ytdl_")
progress_store = {}

def safe_filename(name: str) -> str:
    for ch in r'<>:"/\|?*':
        name = name.replace(ch, "_")
    return name.strip()

def format_size(size) -> str:
    try:
        size = int(size)
        if size >= 1024 ** 3:
            return f"{size / (1024**3):.2f} GB"
        return f"{size / (1024**2):.2f} MB"
    except Exception:
        return "Unknown"

def make_progress_cb(session_id: str, stage: str):
    def cb(stream, chunk, bytes_remaining):
        try:
            total = stream.filesize
            done  = total - bytes_remaining
            pct   = round(done / total * 100, 1) if total else 0
            progress_store[session_id] = {
                "stage":   stage,
                "percent": pct,
                "done":    done,
                "total":   total,
            }
        except Exception:
            pass
    return cb

# ─── Route: /analyse ─────────────────────────────────────────────────────────
@app.route("/analyse", methods=["POST", "OPTIONS"])
def analyse():
    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(force=True, silent=True) or {}
    url  = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "URL parameter missing"}), 400

    try:
        yt        = YouTube(url)
        video_streams = (
            yt.streams
              .filter(adaptive=True, only_video=True)
              .order_by("resolution")
              .desc()
        )

        streams_list = []
        seen = set()
        for s in video_streams:
            res = s.resolution or "?"
            if res in seen:
                continue
            seen.add(res)
            streams_list.append({
                "itag":       s.itag,
                "resolution": res,
                "mime_type":  s.mime_type,
                "size":       format_size(s.filesize),
            })

        return jsonify({
            "title":     yt.title,
            "thumbnail": yt.thumbnail_url,
            "views":     yt.views,
            "author":    yt.author,
            "length":    yt.length,
            "streams":   streams_list,
        })
    except Exception as e:
        return jsonify({"error": f"Analysis crashed: {str(e)}"}), 500

# ─── Route: /download ────────────────────────────────────────────────────────
@app.route("/download", methods=["POST", "OPTIONS"])
def download():
    if request.method == "OPTIONS":
        return "", 204

    data       = request.get_json(force=True, silent=True) or {}
    url        = (data.get("url") or "").strip()
    itag       = data.get("itag")
    session_id = data.get("session_id") or str(uuid.uuid4())

    if not url or not itag:
        return jsonify({"error": "Missing selection arguments"}), 400

    if shutil.which("ffmpeg") is None:
        return jsonify({"error": "FFmpeg binaries missing on host system"}), 500

    work = os.path.join(WORK_DIR, session_id)
    os.makedirs(work, exist_ok=True)

    try:
        progress_store[session_id] = {"stage": "loading", "percent": 0}
        yt_video     = YouTube(url, on_progress_callback=make_progress_cb(session_id, "video"))
        title        = safe_filename(yt_video.title)
        video_stream = yt_video.streams.get_by_itag(int(itag))

        if video_stream is None:
            return jsonify({"error": "Selected itag stream unavailable"}), 400

        video_mime = video_stream.mime_type
        output_ext = "mp4" if "mp4" in video_mime else "mkv"
        audio_mime = "audio/mp4" if "mp4" in video_mime else "audio/webm"

        audio_stream = (
            yt_video.streams
              .filter(adaptive=True, only_audio=True, mime_type=audio_mime)
              .order_by("abr").desc().first()
        ) or (
            yt_video.streams
              .filter(adaptive=True, only_audio=True)
              .order_by("abr").desc().first()
        )

        if audio_stream is None:
            return jsonify({"error": "No companion audio targets available"}), 500

        audio_itag = audio_stream.itag

        # Video stream fetch
        progress_store[session_id] = {"stage": "video", "percent": 0}
        video_ext = video_mime.split("/")[-1]
        vfile     = os.path.join(work, f"video.{video_ext}")
        video_stream.download(output_path=work, filename=f"video.{video_ext}")

        # Audio stream fetch
        progress_store[session_id] = {"stage": "audio", "percent": 0}
        yt_audio      = YouTube(url, on_progress_callback=make_progress_cb(session_id, "audio"))
        audio_stream2 = yt_audio.streams.get_by_itag(audio_itag)
        audio_ext     = audio_stream.mime_type.split("/")[-1]
        afile         = os.path.join(work, f"audio.{audio_ext}")
        audio_stream2.download(output_path=work, filename=f"audio.{audio_ext}")

        # Transcoding process
        progress_store[session_id] = {"stage": "merging", "percent": 99}
        merged_name = f"{title}_{video_stream.resolution}.{output_ext}"
        merged_file = os.path.join(work, merged_name)

        result = subprocess.run(
            ["ffmpeg", "-i", vfile, "-i", afile, "-c", "copy", "-y", merged_file],
            capture_output=True
        )
        if result.returncode != 0:
            return jsonify({"error": "FFmpeg runtime compilation execution failed"}), 500

        progress_store[session_id] = {"stage": "done", "percent": 100}

        @after_this_request
        def cleanup(response):
            def _del():
                time.sleep(30)
                shutil.rmtree(work, ignore_errors=True)
                progress_store.pop(session_id, None)
            threading.Thread(target=_del, daemon=True).start()
            return response

        return send_file(
            merged_file,
            as_attachment=True,
            download_name=merged_name,
            mimetype=f"video/{output_ext}"
        )

    except Exception as e:
        shutil.rmtree(work, ignore_errors=True)
        progress_store.pop(session_id, None)
        return jsonify({"error": str(e)}), 500

# ─── Route: /progress/<session_id> ───────────────────────────────────────────
@app.route("/progress/<session_id>")
def progress(session_id):
    info = progress_store.get(session_id, {"stage": "idle", "percent": 0})
    return jsonify(info)

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=50000)