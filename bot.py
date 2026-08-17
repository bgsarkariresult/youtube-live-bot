import os
import time
import subprocess
import threading
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

# Terminal output unbuffer karne ke liye
sys.stdout.reconfigure(line_buffering=True)

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"YouTube Live Bot is Running!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    print(f"Web server started on port {port}", flush=True)
    server.serve_forever()

def start_streaming():
    STREAM_KEY = os.environ.get("YOUTUBE_STREAM_KEY")
    VIDEO_FILE = "stream_video.mp4"

    if not STREAM_KEY:
        print("CRITICAL ERROR: YOUTUBE_STREAM_KEY Environment Variable is missing in Render!", flush=True)
        return

    if not os.path.exists(VIDEO_FILE):
        print(f"CRITICAL ERROR: File '{VIDEO_FILE}' missing in repository root!", flush=True)
        return

    rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"

    ffmpeg_cmd = [
        'ffmpeg',
        '-re',
        '-stream_loop', '-1',
        '-i', VIDEO_FILE,
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-b:v', '2500k',
        '-maxrate', '3000k',
        '-bufsize', '6000k',
        '-pix_fmt', 'yuv420p',
        '-g', '50',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '44100',
        '-f', 'flv',
        rtmp_url
    ]

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
