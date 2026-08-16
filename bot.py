import os
import time
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# 1. Render Port Binding to keep Web Service alive
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"YouTube Live Bot is Running!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    print(f"Web server started on port {port}")
    server.serve_forever()

# Start HTTP Web Server in background thread immediately
threading.Thread(target=run_web_server, daemon=True).start()

# 2. Check Stream Key and Video File
STREAM_KEY = os.environ.get("YOUTUBE_STREAM_KEY")
VIDEO_FILE = "stream_video.mp4"

if not STREAM_KEY:
    print("Error: YOUTUBE_STREAM_KEY environment variable is missing!")
    while True:
        time.sleep(60)

if not os.path.exists(VIDEO_FILE):
    print(f"Error: File '{VIDEO_FILE}' missing in root directory!")
    while True:
        time.sleep(60)

# 3. Start Live Streaming Loop
rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"

ffmpeg_cmd = [
    'ffmpeg',
    '-re',
    '-stream_loop', '-1',
    '-i', VIDEO_FILE,
    '-c:v', 'libx264',
    '-preset', 'veryfast',
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

print("Starting Live Stream...")
process = subprocess.run(ffmpeg_cmd)

# If FFmpeg crashes or fails, keep container alive to read logs
if process.returncode != 0:
    print(f"FFmpeg exited with error code {process.returncode}")
    while True:
        time.sleep(60)
