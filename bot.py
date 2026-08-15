import os
import subprocess
import time
import schedule
import pytz
from datetime import datetime

# Environment Variables से Stream Key उठाएगा
YOUTUBE_STREAM_KEY = os.environ.get("YOUTUBE_STREAM_KEY")
RTMP_URL = f"rtmp://a.rtmp.youtube.com/live2/{YOUTUBE_STREAM_KEY}"
VIDEO_PATH = "videos/stream_video.mp4" # आपकी अपलोड की गई वीडियो

def start_stream():
    print(f"[{datetime.now()}] Live Stream Starting...")
    
    # FFmpeg command (Zero Re-encoding - High performance)
    cmd = [
        "ffmpeg",
        "-re",
        "-stream_loop", "-1",  # 8 घंटे तक वीडियो लूप में चलेगी
        "-i", VIDEO_PATH,
        "-c:v", "copy",
        "-c:a", "copy",
        "-f", "flv",
        RTMP_URL
    ]
    
    # 8 घंटे (28,800 सेकंड) तक चलाकर प्रोसेस बंद करेगा
    process = subprocess.Popen(cmd)
    time.sleep(28800) # 8 घंटे = 8 * 3600 sec
    process.terminate()
    print(f"[{datetime.now()}] Live Stream Stopped Automatically.")

# IST (India Time) सेट करना
tz = pytz.timezone('Asia/Kolkata')

# रोज़ सुबह 9 बजे Start और शाम 5 बजे (8 घंटे बाद) Stop
schedule.every().day.at("09:00").do(start_stream)

print("Bot is active and waiting for schedule (09:00 AM IST)...")

while True:
    schedule.run_pending()
    time.sleep(30)
