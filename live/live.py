#!/usr/bin/env python3
"""GitHub Actions पर 5 YouTube + 5 Facebook live stream चलाने वाला helper.

Subcommands:
  plan       कौन-कौन से चैनल चलाने हैं (workflow matrix के लिए)
  key        चैनल की वीडियो-लिस्ट का cache key
  guard      वही चैनल पहले से चल रहा हो तो रुक जाना
  prepare    वीडियो डाउनलोड + एक जैसे format (720p) में तैयार करना
  wait-prev  पिछला 6-घंटे वाला session खत्म होने तक रुकना (handoff)
  stream     ffmpeg से YouTube + Facebook पर एक साथ live भेजना
  watchdog   जो चैनल नहीं चल रहा उसे दोबारा शुरू करना

सिर्फ standard library इस्तेमाल होती है. बाहर से चाहिए: ffmpeg, ffprobe, yt-dlp, gh.
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "channels.json"
MEDIA = ROOT / "media"
WORKFLOW = "live-stream.yml"

# GitHub Actions का एक job ज़्यादा से ज़्यादा 6 घंटे चलता है (timeout 355 मिनट रखा है).
JOB_BUDGET = 350 * 60          # job शुरू होने के बाद कुल इतना समय इस्तेमाल करेंगे
MAX_STREAM = 325 * 60          # एक session में ज़्यादा से ज़्यादा इतनी देर stream
HANDOFF_BEFORE_END = 25 * 60   # session खत्म होने से 25 मिनट पहले अगला session शुरू
CACHE_VERSION = "v1"
END_TOLERANCE = 15              # इतने सेकंड पहले खत्म हुआ तो भी session पूरा मानें


def log(msg):
    print(msg, flush=True)


def set_output(key, value):
    line = f"{key}={value}"
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    log(line)


def run(cmd, **kw):
    return subprocess.run(cmd, text=True, **kw)


def load_channels():
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    out = {}
    for ch in data.get("channels", []):
        cid = int(ch["id"])
        vids = [str(v).strip() for v in ch.get("videos", []) if str(v).strip()]
        out[cid] = {"id": cid, "name": ch.get("name", f"Channel {cid}"), "videos": vids}
    return out


def get_channel(cid):
    chans = load_channels()
    if cid not in chans:
        sys.exit(f"ERROR: channels.json में channel {cid} नहीं मिला")
    return chans[cid]


def parse_selection(text):
    text = (text or "").strip().lower()
    if text in ("", "all"):
        return None
    return {int(x) for x in text.replace(" ", "").split(",") if x}


def repo():
    return os.environ.get("GITHUB_REPOSITORY", "")


def gh(args):
    cmd = ["gh", *args]
    if repo():
        cmd += ["-R", repo()] if args[0] in ("run", "workflow") else []
    return run(cmd, capture_output=True)


# ---------------------------------------------------------------- plan / key

def cmd_plan(a):
    if os.environ.get("STREAMING_ENABLED", "").strip().lower() == "false":
        log("STREAMING_ENABLED=false है, इसलिए कोई stream शुरू नहीं होगी.")
        ids = []
    else:
        want = parse_selection(a.channel)
        ids = [c["id"] for c in sorted(load_channels().values(), key=lambda c: c["id"])
               if c["videos"] and (want is None or c["id"] in want)]
        if not ids:
            log("चुने हुए चैनल की 'videos' लिस्ट खाली है (channels.json देखें).")
    set_output("channels", json.dumps(ids))


def local_path(src):
    p = Path(src)
    return p if p.is_absolute() else ROOT / p


def cmd_key(a):
    ch = get_channel(a.channel)
    parts = [CACHE_VERSION]
    for v in ch["videos"]:
        if v.startswith(("http://", "https://")):
            parts.append(v)
        else:
            p = local_path(v)
            parts.append(f"{v}:{p.stat().st_size if p.exists() else 0}")
    set_output("key", hashlib.sha1("\n".join(parts).encode()).hexdigest()[:16])


# --------------------------------------------------------------------- guard

def active_titles():
    """चल रहे / कतार में लगे live-stream runs: [(run_id, title)]"""
    seen = {}
    for status in ("in_progress", "queued", "waiting", "pending", "requested"):
        r = gh(["run", "list", "--workflow", WORKFLOW, "--status", status,
                "--json", "databaseId,displayTitle", "--limit", "100"])
        if r.returncode != 0:
            continue
        try:
            for item in json.loads(r.stdout or "[]"):
                seen[int(item["databaseId"])] = item["displayTitle"]
        except (ValueError, KeyError):
            pass
    return seen


def title_covers(title):
    """'Live: all' -> None (सब), 'Live: 1,3' -> {1,3}"""
    if not title.startswith("Live:"):
        return set()
    return parse_selection(title.split(":", 1)[1])


def cmd_guard(a):
    me = int(os.environ.get("GITHUB_RUN_ID", "0"))
    prev = os.environ.get("PREV_RUN_ID", "").strip()
    prev = int(prev) if prev.isdigit() else None
    for rid, title in active_titles().items():
        if rid >= me or rid == prev:
            continue  # सिर्फ़ पुराने runs देखें (handoff वाला पिछला run छोड़कर)
        cov = title_covers(title)
        if cov is None or a.channel in cov:
            sys.exit(f"ERROR: Channel {a.channel} पहले से चल रहा है (run {rid}: '{title}'). "
                     "एक ही stream key पर दो stream नहीं चलाते. यह run रोका जा रहा है.")
    log("कोई duplicate नहीं मिला.")


# ------------------------------------------------------------------- prepare

def ytdlp_supports(flag):
    r = run(["yt-dlp", "--help"], capture_output=True)
    return flag in (r.stdout or "")


def download(src, raw_dir, idx):
    if not src.startswith(("http://", "https://")):
        p = local_path(src)
        if not p.exists():
            raise RuntimeError(f"फ़ाइल नहीं मिली: {src}")
        return p

    cmd = ["yt-dlp", "--no-playlist", "--no-progress", "--retries", "5",
           "-f", "bv*[height<=720]+ba/b[height<=720]/b",
           "--merge-output-format", "mp4",
           "-o", str(raw_dir / f"{idx:03d}.%(ext)s")]
    if ytdlp_supports("--js-runtimes"):
        cmd += ["--js-runtimes", "node"]
    cookie_file = None
    try:
        cookies = os.environ.get("YT_COOKIES", "").strip()
        if cookies:
            fd, cookie_file = tempfile.mkstemp(suffix=".txt")
            with os.fdopen(fd, "w") as fh:
                fh.write(cookies + "\n")
            cmd += ["--cookies", cookie_file]
        cmd.append(src)
        r = run(cmd)
        if r.returncode != 0:
            raise RuntimeError(f"yt-dlp fail हुआ (code {r.returncode}). YouTube कई बार GitHub के "
                               "servers को block करता है; README में YT_COOKIES वाला तरीका देखें.")
    finally:
        if cookie_file:
            os.unlink(cookie_file)
    files = [f for f in raw_dir.glob(f"{idx:03d}.*") if f.suffix not in (".part", ".ytdl")]
    if not files:
        raise RuntimeError("डाउनलोड के बाद फ़ाइल नहीं मिली")
    return max(files, key=lambda f: f.stat().st_size)


def has_audio(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index", "-of", "csv=p=0", str(path)], capture_output=True)
    return bool((r.stdout or "").strip())


def normalize(src, dst):
    """सारी वीडियो एक जैसे format में, ताकि stream में बिना re-encode (copy) जुड़ सकें."""
    vf = ("scale=1280:720:force_original_aspect_ratio=decrease,"
          "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if has_audio(src):
        maps = ["-map", "0:v:0", "-map", "0:a:0"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        maps = ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += maps + ["-vf", vf,
                   "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
                   "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k",
                   "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
                   "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
                   "-movflags", "+faststart", str(dst)]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg normalize fail (code {r.returncode})")


def cmd_prepare(a):
    ch = get_channel(a.channel)
    out = MEDIA / f"ch{ch['id']}"
    raw = MEDIA / f"raw{ch['id']}"
    shutil.rmtree(out, ignore_errors=True)
    shutil.rmtree(raw, ignore_errors=True)
    out.mkdir(parents=True)
    ok = 0
    for i, src in enumerate(ch["videos"], 1):
        raw.mkdir(parents=True, exist_ok=True)
        log(f"[{i}/{len(ch['videos'])}] तैयार कर रहा हूँ: {src}")
        try:
            path = download(src, raw, i)
            normalize(path, out / f"{i:03d}.mp4")
            ok += 1
        except Exception as exc:  # एक वीडियो खराब हो तो बाकी चलती रहें
            log(f"WARNING: वीडियो {i} छोड़ी गई: {exc}")
        finally:
            shutil.rmtree(raw, ignore_errors=True)
    if ok == 0:
        sys.exit("ERROR: एक भी वीडियो तैयार नहीं हो पाई.")
    log(f"Channel {ch['id']}: {ok}/{len(ch['videos'])} वीडियो तैयार.")


# ------------------------------------------------------------------ wait-prev

def cmd_wait_prev(a):
    prev = os.environ.get("PREV_RUN_ID", "").strip()
    if not prev:
        return
    job = f"Channel {a.channel}"
    log(f"पिछले session (run {prev}, '{job}') के खत्म होने का इंतज़ार...")
    deadline = time.time() + 40 * 60
    fails, last_print = 0, 0.0
    jq = f'[.jobs[] | select(.name=="{job}") | .status] | first // "missing"'
    while time.time() < deadline:
        r = run(["gh", "api", f"repos/{repo()}/actions/runs/{prev}/jobs?per_page=100", "--jq", jq],
                capture_output=True)
        if r.returncode != 0:
            fails += 1
            if fails >= 3:
                log("पिछला run पढ़ नहीं पाया, सीधे शुरू कर रहा हूँ.")
                return
        else:
            fails = 0
            status = (r.stdout or "").strip()
            if status in ("completed", "missing"):
                log("पिछला session खत्म हो गया, अब मेरी बारी.")
                return
            if time.time() - last_print > 60:
                log(f"पिछले session की स्थिति: {status}")
                last_print = time.time()
        time.sleep(5)
    log("इंतज़ार की सीमा पूरी हुई, शुरू कर रहा हूँ.")


# -------------------------------------------------------------------- stream

def probe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)], capture_output=True)
    try:
        return float((r.stdout or "").strip())
    except ValueError:
        return 0.0


def build_playlist(cid, seconds_needed, name="list.txt"):
    d = MEDIA / f"ch{cid}"
    files = sorted(d.glob("[0-9][0-9][0-9].mp4"))
    if not files:
        sys.exit(f"ERROR: media/ch{cid} में तैयार वीडियो नहीं हैं.")
    total = sum(probe_duration(f) for f in files)
    if total <= 0:
        sys.exit("ERROR: वीडियो की लंबाई पढ़ी नहीं जा सकी.")
    repeats = math.ceil(seconds_needed / total) + 1
    lines = [f"file '{f}'" for _ in range(repeats) for f in files]
    lst = d / name
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"Playlist: {len(files)} वीडियो ({total/60:.1f} मिनट) x {repeats} बार")
    return lst


def handoff(cid):
    """अगला 6-घंटे का session अभी शुरू करवाना; वह हमारे खत्म होने तक रुका रहेगा."""
    log("अगला session शुरू करवा रहा हूँ (handoff)...")
    cmd = ["gh", "workflow", "run", WORKFLOW, "-R", repo(),
           "--ref", os.environ.get("GITHUB_REF_NAME", "main"),
           "-f", f"channel={cid}", "-f", f"prev_run_id={os.environ.get('GITHUB_RUN_ID', '')}"]
    for _ in range(5):
        r = run(cmd, capture_output=True)
        if r.returncode == 0:
            log("अगला session कतार में लग गया.")
            return True
        log(f"handoff fail: {(r.stderr or '').strip()}")
        time.sleep(15)
    log("WARNING: handoff नहीं हो पाया; watchdog (अगर चालू है) दोबारा शुरू कर देगा.")
    return False


def cmd_stream(a):
    cid = a.channel
    yt = os.environ.get("YT_STREAM_KEY", "").strip()
    fb = os.environ.get("FB_STREAM_KEY", "").strip()
    for secret in (yt, fb):
        if secret:
            print(f"::add-mask::{secret}", flush=True)

    if a.dry_run:
        targets = [str(MEDIA / "dry-run.flv")]
        names = ["dry-run"]
    else:
        targets, names = [], []
        if yt:
            targets.append(f"rtmp://a.rtmp.youtube.com/live2/{yt}")
            names.append("YouTube")
        if fb:
            targets.append(f"rtmps://live-api-s.facebook.com:443/rtmp/{fb}")
            names.append("Facebook")
        if not targets:
            sys.exit(f"ERROR: YT_STREAM_KEY_{cid} और FB_STREAM_KEY_{cid} दोनों secrets खाली हैं.")

    now = time.time()
    job_start = float(os.environ.get("LIVE_JOB_START") or now)
    remaining = min(MAX_STREAM, job_start + JOB_BUDGET - now)
    if a.duration:
        remaining = float(a.duration)
    end_at = now + remaining
    do_handoff = (not a.no_handoff) and remaining > HANDOFF_BEFORE_END + 300
    handoff_at = end_at - HANDOFF_BEFORE_END
    handed = False
    log(f"Channel {cid} -> {', '.join(names)} | इस session में {remaining/60:.0f} मिनट stream होगी")

    # हर platform के लिए अलग ffmpeg process: एक की stream टूटे तो दूसरी पर असर नहीं पड़ता.
    state = {n: {"proc": None, "start": 0.0, "fails": 0, "retry_at": 0.0, "id": i}
             for i, n in enumerate(names)}

    def launch(i, name, target):
        left = int(end_at - time.time())
        lst = build_playlist(cid, left, f"list_{i}.txt")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-nostats",
               "-re", "-f", "concat", "-safe", "0", "-i", str(lst),
               "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
               "-t", str(left), "-f", "flv", target]
        log(f"[{name}] ffmpeg शुरू (बचा समय {left//60} मिनट)")
        return subprocess.Popen(cmd)

    while time.time() < end_at - END_TOLERANCE:
        for i, (name, target) in enumerate(zip(names, targets)):
            st = state[name]
            proc = st["proc"]
            if proc is not None and proc.poll() is not None:
                ran = time.time() - st["start"]
                st["fails"] = st["fails"] + 1 if ran < 30 else 0
                if time.time() < end_at - END_TOLERANCE:
                    log(f"[{name}] ffmpeg जल्दी रुक गया (code {proc.returncode}, {ran:.0f}s). 10 सेकंड बाद दोबारा...")
                st["proc"] = None
                st["retry_at"] = time.time() + 10
            if st["proc"] is None and time.time() >= st["retry_at"]:
                if st["fails"] >= 8:
                    for other in state.values():
                        if other["proc"] is not None:
                            other["proc"].terminate()
                    sys.exit(f"ERROR: [{name}] बार-बार connect नहीं हो पा रहा. Stream key / नेटवर्क जाँचें.")
                st["proc"] = launch(i, name, target)
                st["start"] = time.time()
        if do_handoff and not handed and time.time() >= handoff_at:
            handed = handoff(cid) or True
        time.sleep(2)

    for st in state.values():  # -t की वजह से अपने-आप रुकते हैं; थोड़ा इंतज़ार करके बंद करें
        if st["proc"] is not None:
            try:
                st["proc"].wait(timeout=30)
            except subprocess.TimeoutExpired:
                st["proc"].terminate()

    log("Session पूरा हुआ.")


# ------------------------------------------------------------------ watchdog

def cmd_watchdog(a):
    covered = set()
    for _, title in active_titles().items():
        cov = title_covers(title)
        if cov is None:
            log("एक 'Live: all' run चल रहा है; कुछ करने की ज़रूरत नहीं.")
            return
        covered |= cov
    for ch in sorted(load_channels().values(), key=lambda c: c["id"]):
        if not ch["videos"] or ch["id"] in covered:
            continue
        log(f"Channel {ch['id']} नहीं चल रहा; शुरू कर रहा हूँ.")
        r = gh(["workflow", "run", WORKFLOW, "--ref", os.environ.get("GITHUB_REF_NAME", "main"),
                "-f", f"channel={ch['id']}"])
        if r.returncode != 0:
            log(f"शुरू नहीं हो पाया: {(r.stderr or '').strip()}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, channel_type=int, with_channel=True):
        sp = sub.add_parser(name)
        if with_channel:
            sp.add_argument("--channel", type=channel_type, required=True)
        sp.set_defaults(fn=fn)
        return sp

    add("plan", cmd_plan, channel_type=str)
    add("key", cmd_key)
    add("guard", cmd_guard)
    add("prepare", cmd_prepare)
    add("wait-prev", cmd_wait_prev)
    sp = add("stream", cmd_stream)
    sp.add_argument("--dry-run", action="store_true", help="असली RTMP की जगह लोकल फ़ाइल में लिखें")
    sp.add_argument("--duration", type=float, help="सेकंड (टेस्ट के लिए)")
    sp.add_argument("--no-handoff", action="store_true")
    add("watchdog", cmd_watchdog, with_channel=False)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
