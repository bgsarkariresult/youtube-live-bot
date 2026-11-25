import os
import glob
import time
import subprocess
from flask import Flask
from threading import Thread

app = Flask(__name__)

# Live session ki maximum duration: 6 hours
STREAM_DURATION_SECONDS = 6 * 60 * 60


@app.route('/')
def home():
    return "Stream Bot is Running (6-hour Live session)!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)


def generate_playlist():
    """ऑटोमैटिक सभी .mp4 फ़ाइलों को ढूँढकर list.txt तैयार करेगा"""
    video_files = sorted(glob.glob("*.mp4"))
    if not video_files:
        print("ERROR: No .mp4 files found in repository!", flush=True)
        return False

    with open("list.txt", "w") as f:
        for video in video_files:
            f.write(f"file '{video}'\n")

    print(f"Generated playlist with {len(video_files)} videos: {video_files}", flush=True)
    return True


def start_streaming():
    yt_key = os.environ.get("YT_STREAM_KEY")
    fb_key = os.environ.get("FB_STREAM_KEY")

    yt_url = f"rtmp://a.rtmp.youtube.com/live2/{yt_key}" if yt_key else None
    fb_url = f"rtmps://live-api-s.facebook.com:443/rtmp/{fb_key}" if fb_key else None

    if not yt_url and not fb_url:
        print("ERROR: Neither YT_STREAM_KEY nor FB_STREAM_KEY is set in Environment Variables!", flush=True)
        return

    # Timer ek hi baar start hota hai; reconnect hone par bhi total 6-hour limit nahi badhegi.
    deadline = time.monotonic() + STREAM_DURATION_SECONDS
    print("6-hour Live session started. It will not auto-restart after completion.", flush=True)

    while time.monotonic() < deadline:
        if not generate_playlist():
            time.sleep(min(10, max(0, deadline - time.monotonic())))
            continue

        remaining_seconds = max(1, int(deadline - time.monotonic()))
        print(f"Starting FFmpeg Live Streaming. Remaining session time: {remaining_seconds} seconds", flush=True)

        # CASE 1: YouTube only (direct copy mode)
        if yt_url and not fb_url:
            print("Mode: YouTube ONLY (Direct Pass-through)", flush=True)
            ffmpeg_cmd = [
                'ffmpeg',
                '-re',
                '-f', 'concat',
                '-safe', '0',
                '-stream_loop', '-1',
                '-i', 'list.txt',
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-t', str(remaining_seconds),
                '-f', 'flv',
                yt_url
            ]

        # CASE 2: Facebook only (direct copy mode)
        elif fb_url and not yt_url:
            print("Mode: Facebook ONLY (Copy Mode)", flush=True)
            ffmpeg_cmd = [
                'ffmpeg',
                '-re',
                '-f', 'concat',
                '-safe', '0',
                '-stream_loop', '-1',
                '-i', 'list.txt',
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-bsf:v', 'h264_mp4toannexb',
                '-t', str(remaining_seconds),
                '-f', 'flv',
                fb_url
            ]

        # CASE 3: YouTube + Facebook together
        else:
            print("Mode: BOTH YouTube and Facebook (Dual Stream)", flush=True)
            tee_map = f"[onfail=ignore:f=flv]{yt_url}|[onfail=ignore:f=flv]{fb_url}"
            ffmpeg_cmd = [
                'ffmpeg',
                '-re',
                '-f', 'concat',
                '-safe', '0',
                '-stream_loop', '-1',
                '-i', 'list.txt',
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-tune', 'zerolatency',
                '-vf', 'scale=1280:720',
                '-b:v', '1200k',
                '-maxrate', '1500k',
                '-bufsize', '2500k',
                '-g', '48',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-ar', '44100',
                '-t', str(remaining_seconds),
                '-f', 'tee',
                '-map', '0:v',
                '-map', '0:a',
                tee_map
            ]

        process = subprocess.Popen(ffmpeg_cmd)
        process.wait()

        if time.monotonic() >= deadline:
            print("6-hour Live session completed. Streaming stopped; no automatic restart.", flush=True)
            break

        print(f"FFmpeg stopped early (Exit Code: {process.returncode}). Reconnecting while session time remains...", flush=True)
        time.sleep(min(5, max(0, deadline - time.monotonic())))

    print("Live session ended. Start the bot again manually for another session.", flush=True)


if __name__ == "__main__":
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

    start_streaming()
