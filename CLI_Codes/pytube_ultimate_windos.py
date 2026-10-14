import os
import sys
import shutil
import subprocess
from datetime import datetime
from pytubefix import YouTube

# =====================================================
# CONFIGURATION (Windows Path Style)
# =====================================================

# Using a raw string (r"...") so Windows backslashes don't break things.
# Feel free to change this to your desired Windows directory.
BASE_DIR = r"C:\Users\Public\Downloads\Pytube"

VIDEO_DIR = os.path.join(BASE_DIR, "Video")
AUDIO_DIR = os.path.join(BASE_DIR, "Audio")
MERGED_DIR = os.path.join(BASE_DIR, "Merged")

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(MERGED_DIR, exist_ok=True)

# =====================================================
# PROGRESS CALLBACK
# =====================================================

def on_progress(stream, chunk, bytes_remaining):
    try:
        total_size = stream.filesize
        downloaded = total_size - bytes_remaining

        if total_size == 0:
            return

        percentage = downloaded / total_size * 100

        bar_length = 30
        filled = int(bar_length * percentage / 100)
        # Using a standard block character compatible with standard Windows CMD
        bar = "█" * filled + "-" * (bar_length - filled)

        stream_type = (
            "VIDEO"
            if getattr(stream, "includes_video_track", False)
            else "AUDIO"
        )

        print(
            f"\r{stream_type} [{bar}] "
            f"{percentage:6.2f}% "
            f"({downloaded/(1024*1024):.2f}MB/"
            f"{total_size/(1024*1024):.2f}MB)",
            end="",
            flush=True
        )

    except Exception:
        pass

# =====================================================
# UNIQUE FILE NAME
# =====================================================

def unique_path(path):
    if not os.path.exists(path):
        return path

    base, ext = os.path.splitext(path)
    counter = 1

    while True:
        new_path = f"{base} ({counter}){ext}"

        if not os.path.exists(new_path):
            return new_path

        counter += 1

# =====================================================
# SAFE TITLE (Windows File System Rules)
# =====================================================

def safe_filename(name):
    # Enforces Windows strict filename rules
    invalid = '<>:"/\\|?*'

    for ch in invalid:
        name = name.replace(ch, "_")

    return name.strip()

# =====================================================
# FILE SIZE FORMATTER
# =====================================================

def format_size(size):
    try:
        return f"{size / (1024 * 1024):.2f} MB"
    except Exception:
        return "Unknown"

# =====================================================
# MAIN PROGRAM
# =====================================================

def main():

    print("=" * 100)
    print("PYTUBEFIX YOUTUBE DOWNLOADER (WINDOWS EDITION)")
    print("=" * 100)

    # -------------------------------------------------
    # FFMPEG CHECK
    # -------------------------------------------------

    if shutil.which("ffmpeg") is None:
        print("\nFFmpeg not found in your System PATH.")
        print("Please download FFmpeg and add it to your Windows Environment Variables.")
        print("Alternatively, install via winget: winget install Gyan.FFmpeg")
        sys.exit()

    # -------------------------------------------------
    # URL INPUT
    # -------------------------------------------------

    url = input("\nEnter YouTube URL: ").strip()

    if not url:
        print("URL cannot be empty.")
        sys.exit()

    # -------------------------------------------------
    # LOAD VIDEO
    # -------------------------------------------------

    try:
        yt = YouTube(
            url,
            on_progress_callback=on_progress
        )

        title = safe_filename(yt.title)

        print("\n" + "=" * 100)
        # safe print for Windows terminals that might choke on foreign characters or emojis
        try:
            print("TITLE :", title)
        except UnicodeEncodeError:
            print("TITLE :", title.encode('ascii', 'ignore').decode('ascii'))
        print("=" * 100)

    except Exception as e:
        print(f"\nFailed to load video.\nReason: {e}")
        sys.exit()

    # -------------------------------------------------
    # VIDEO STREAMS (TABLE FORMAT)
    # -------------------------------------------------

    video_streams = (
        yt.streams
        .filter(adaptive=True, only_video=True)
        .order_by("resolution")
        .desc()
    )

    print("\nAVAILABLE VIDEO STREAMS:")
    
    # Table Header Boundary
    print("+" + "-"*7 + "+" + "-"*12 + "+" + "-"*15 + "+" + "-"*20 + "+" + "-"*12 + "+")
    print(f"| {'itag':^5} | {'Resolution':^10} | {'Format':^13} | {'Codec':^18} | {'Size':^10} |")
    print("+" + "-"*7 + "+" + "-"*12 + "+" + "-"*15 + "+" + "-"*20 + "+" + "-"*12 + "+")

    found_video = False

    for stream in video_streams:
        found_video = True
        try:
            codec = stream.video_codec if stream.video_codec else "Unknown"
            
            print(
                f"| {stream.itag:<5} "
                f"| {str(stream.resolution):<10} "
                f"| {stream.mime_type.split('/')[-1]:<13} "
                f"| {codec:<18} "
                f"| {format_size(stream.filesize):>10} |"
            )
        except Exception:
            pass

    # Table Footer Boundary
    print("+" + "-"*7 + "+" + "-"*12 + "+" + "-"*15 + "+" + "-"*20 + "+" + "-"*12 + "+")

    if not found_video:
        print("No video streams found.")
        sys.exit()

    # -------------------------------------------------
    # USER CHOICE
    # -------------------------------------------------

    try:
        video_itag = int(
            input("\nEnter Video itag : ")
        )
    except ValueError:
        print("itag must be numeric.")
        sys.exit()

    video_stream = yt.streams.get_by_itag(video_itag)

    if video_stream is None:
        print("Invalid video itag.")
        sys.exit()

    # -------------------------------------------------
    # AUTO AUDIO SELECTION
    # -------------------------------------------------

    video_mime = video_stream.mime_type

    if "video/mp4" in video_mime:

        audio_stream = (
            yt.streams
            .filter(
                adaptive=True,
                only_audio=True,
                mime_type="audio/mp4"
            )
            .order_by("abr")
            .desc()
            .first()
        )

        output_ext = "mp4"

    elif "video/webm" in video_mime:

        audio_stream = (
            yt.streams
            .filter(
                adaptive=True,
                only_audio=True,
                mime_type="audio/webm"
            )
            .order_by("abr")
            .desc()
            .first()
        )

        output_ext = "mkv"

    else:

        audio_stream = (
            yt.streams
            .filter(adaptive=True, only_audio=True)
            .order_by("abr")
            .desc()
            .first()
        )

        output_ext = "mkv"

    if audio_stream is None:
        print("No compatible audio stream found.")
        sys.exit()

    print("\nSelected Audio")
    print(
        f"itag:{audio_stream.itag} | "
        f"{audio_stream.abr} | "
        f"{audio_stream.mime_type}"
    )

    # -------------------------------------------------
    # FILE NAMES
    # -------------------------------------------------

    video_ext = video_stream.mime_type.split("/")[-1]
    audio_ext = audio_stream.mime_type.split("/")[-1]

    video_name = f"{title} {video_stream.resolution}_VIDEO.{video_ext}"
    audio_name = f"{title} {audio_stream.abr}_AUDIO.{audio_ext}"
    merged_name = f"{title} {video_stream.resolution}.{output_ext}"

    video_file = unique_path(
        os.path.join(VIDEO_DIR, video_name)
    )

    audio_file = unique_path(
        os.path.join(AUDIO_DIR, audio_name)
    )

    merged_file = unique_path(
        os.path.join(MERGED_DIR, merged_name)
    )

    # -------------------------------------------------
    # DOWNLOAD VIDEO
    # -------------------------------------------------

    print("\n\nDownloading Video...")

    try:
        video_path = video_stream.download(
            output_path=os.path.dirname(video_file),
            filename=os.path.basename(video_file)
        )
    except Exception as e:
        print(f"\nVideo download failed: {e}")
        sys.exit()

    print("\nVideo download complete.")

    # -------------------------------------------------
    # DOWNLOAD AUDIO
    # -------------------------------------------------

    print("\nDownloading Audio...")

    try:
        audio_path = audio_stream.download(
            output_path=os.path.dirname(audio_file),
            filename=os.path.basename(audio_file)
        )
    except Exception as e:
        print(f"\nAudio download failed: {e}")
        sys.exit()

    print("\nAudio download complete.")

    # -------------------------------------------------
    # MERGE (With Windows-specific Background flags)
    # -------------------------------------------------

    print("\nMerging...")

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i", video_path,
                "-i", audio_path,
                "-c", "copy",
                "-y",
                merged_file
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Windows specific flag: Prevents a black CMD window popping up during processing
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

    except subprocess.CalledProcessError:
        print("FFmpeg merge failed.")
        sys.exit()

    # -------------------------------------------------
    # RESULTS
    # -------------------------------------------------

    print("\n" + "=" * 100)
    print("DOWNLOAD COMPLETED")
    print("=" * 100)

    try:
        print(f"\nVideo File:\n{video_path}")
        print(f"\nAudio File:\n{audio_path}")
        print(f"\nMerged File:\n{merged_file}")
    except UnicodeEncodeError:
        # Fallback if the path string throws an encoding error in Windows CMD
        print(f"\nVideo File:\n{video_path.encode('ascii', 'ignore').decode('ascii')}")
        print(f"\nAudio File:\n{audio_path.encode('ascii', 'ignore').decode('ascii')}")
        print(f"\nMerged File:\n{merged_file.encode('ascii', 'ignore').decode('ascii')}")

    print("\nFinished at:", datetime.now())

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")

    except PermissionError:
        print("\nPermission denied. Run the script/terminal as administrator or fix directory permissions.")

    except FileNotFoundError as e:
        print(f"\nFile not found: {e}")

    except OSError as e:
        print(f"\nOS Error: {e}")

    except Exception as e:
        print(f"\nUnexpected Error: {e}")