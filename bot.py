import os
import time
import subprocess
import threading
import sys
import glob
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.stdout.reconfigure(line_buffering=True)

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Live Bot is Active!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    print(f"Web server started on port {port}", flush=True)
    server.serve_forever()

def prepare_playlist():
    video_files = sorted(glob.glob("*.mp4"))
    if not video_files:
        print("CRITICAL ERROR: No .mp4 video files found!", flush=True)
        return False

    print(f"Found {len(video_files)} video(s): {', '.join(video_files)}", flush=True)
    with open("list.txt", "w") as f:
        for video in video_files:
            f.write(f"file '{video}'\n")
    return True

def start_streaming():
    YT_KEY = os.environ.get("YOUTUBE_STREAM_KEY", "").strip()
    FB_KEY = os.environ.get("FB_STREAM_KEY", "").strip()

    if not YT_KEY and not FB_KEY:
        print("CRITICAL ERROR: No stream keys provided!", flush=True)
        return

    if not prepare_playlist():
        return

    yt_url = f"rtmp://a.rtmp.youtube.com/live2/{YT_KEY}" if YT_KEY else None
    fb_url = f"rtmps://live-api-s.facebook.com:443/rtmp/{FB_KEY}" if FB_KEY else None

# Optimized FFmpeg Settings - Fixes FLV Tag Error & Low CPU Load
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
        '-profile:v', 'baseline',      # RTMP streaming compatibility
        '-b:v', '1500k',               # Stable Bitrate (No buffering)
        '-maxrate', '1800k',
        '-bufsize', '3000k',
        '-g', '48',
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '44100'
    ]
    if yt_url and fb_url:
        print("Streaming to BOTH YouTube and Facebook...", flush=True)
        tee_map = f"[f=flv]{yt_url}|[f=flv]{fb_url}"
        ffmpeg_cmd.extend(['-f', 'tee', '-map', '0:v', '-map', '0:a', tee_map])
    elif yt_url:
        print("Streaming to YouTube ONLY...", flush=True)
        ffmpeg_cmd.extend(['-f', 'flv', yt_url])
    elif fb_url:
        print("Streaming to Facebook ONLY...", flush=True)
        ffmpeg_cmd.extend(['-f', 'flv', fb_url])

    while True:
        print("Starting FFmpeg Live Streaming...", flush=True)
        process = subprocess.Popen(ffmpeg_cmd)
        process.wait()
        print(f"FFmpeg stopped (Exit Code: {process.returncode}). Reconnecting in 5 seconds...", flush=True)
        time.sleep(5)

if __name__ == '__main__':
    stream_thread = threading.Thread(target=start_streaming)
    stream_thread.daemon = True
    stream_thread.start()

    run_web_server()
