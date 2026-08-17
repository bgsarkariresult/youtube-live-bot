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
    # .mp4 वाली सभी फ़ाइलों को ढूँढता है (उदा: video1.mp4, video2.mp4 या stream_video.mp4)
    video_files = sorted(glob.glob("*.mp4"))
    
    if not video_files:
        print("CRITICAL ERROR: No .mp4 video files found in the directory!", flush=True)
        return False

    print(f"Found {len(video_files)} video(s): {', '.join(video_files)}", flush=True)

    # list.txt फ़ाइल तैयार करता है (FFmpeg concat के लिए)
    with open("list.txt", "w") as f:
        for video in video_files:
            f.write(f"file '{video}'\n")
    return True

def start_streaming():
    YT_KEY = os.environ.get("YOUTUBE_STREAM_KEY", "").strip()
    FB_KEY = os.environ.get("FB_STREAM_KEY", "").strip()

    if not YT_KEY and not FB_KEY:
        print("CRITICAL ERROR: Neither YOUTUBE_STREAM_KEY nor FB_STREAM_KEY is provided!", flush=True)
        return

    if not prepare_playlist():
        return

    # RTMP URLs
    yt_url = f"rtmp://a.rtmp.youtube.com/live2/{YT_KEY}" if YT_KEY else None
    fb_url = f"rtmps://live-api-s.facebook.com:443/rtmp/{FB_KEY}" if FB_KEY else None

    # Base FFmpeg command
    ffmpeg_cmd = [
        'ffmpeg',
        '-re',
        '-f', 'concat',
        '-safe', '0',
        '-stream_loop', '-1',
        '-i', 'list.txt',
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '44100'
    ]

    # अगर दोनों keys हैं तो एक साथ YouTube और FB दोनों पर टेलीकास्ट होगा
    if yt_url and fb_url:
        print("Streaming to BOTH YouTube and Facebook...", flush=True)
        ffmpeg_cmd.extend([
            '-f', 'flv', yt_url,
            '-f', 'flv', fb_url
        ])
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
