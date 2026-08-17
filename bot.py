import os
import glob
import time
import subprocess
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "Stream Bot is Running Active 24/7!"

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
        print("ERROR: Neither YT_STREAM_KEY nor FB_STREAM_KEY is set in Environment Variables!")
        return

    while True:
        # 1. लिस्ट तैयार करें
        if not generate_playlist():
            time.sleep(10)
            continue

        print("Starting FFmpeg Live Streaming...", flush=True)

        # -------------------------------------------------------------
        # CASE 1: Keval YouTube Par Chalana Ho (1080p Copy Mode)
        # -------------------------------------------------------------
        if yt_url and not fb_url:
            print("Mode: YouTube ONLY (High Speed Direct Pass-through)", flush=True)
            ffmpeg_cmd = [
                'ffmpeg',
                '-re',
                '-f', 'concat',
                '-safe', '0',
                '-stream_loop', '-1',
                '-i', 'list.txt',
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-f', 'flv',
                yt_url
            ]

        # -------------------------------------------------------------
        # CASE 2: Keval Facebook Par Chalana Ho (Zero CPU Copy Mode)
        # -------------------------------------------------------------
        elif fb_url and not yt_url:
            print("Mode: Facebook ONLY (Ultra-Fast Copy Mode)", flush=True)
            ffmpeg_cmd = [
                'ffmpeg',
                '-re',
                '-f', 'concat',
                '-safe', '0',
                '-stream_loop', '-1',
                '-i', 'list.txt',
                '-c:v', 'copy',            # Zero CPU Load - Original Bitrate & FPS
                '-c:a', 'copy',            # Zero CPU Load
                '-bsf:v', 'h264_mp4toannexb', # Fixes Facebook FLV stream compatibility
                '-f', 'flv',
                fb_url
            ]

        # -------------------------------------------------------------
        # CASE 3: YouTube + Facebook Dono Par Chalana Ho
        # -------------------------------------------------------------
        else:
            print("Mode: BOTH YouTube and Facebook (Low CPU Dual Stream)", flush=True)
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
                '-f', 'tee',
                '-map', '0:v',
                '-map', '0:a',
                tee_map
            ]

        process = subprocess.Popen(ffmpeg_cmd)
        process.wait()

        print(f"FFmpeg stopped (Exit Code: {process.returncode}). Reconnecting in 5 seconds...", flush=True)
        time.sleep(5)

if __name__ == "__main__":
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    start_streaming()
