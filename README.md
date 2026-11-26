# 24x7 Live Stream (5 YouTube + 5 Facebook) — GitHub Actions

हर चैनल अपना अलग job है: वह `channels.json` की वीडियो को लूप में चलाता है और **YouTube और Facebook दोनों पर एक साथ** live भेजता है (video copy mode में, यानी CPU कम लगता है).
एक Actions job 6 घंटे में बंद हो जाता है, इसलिए हर session खत्म होने से 25 मिनट पहले अगला session खुद शुरू कर देता है। `Live Watchdog` हर 30 मिनट में जाँचता है कि कोई चैनल गिरा तो नहीं।

## ज़रूरी चेतावनी
- **Private repo में फ्री मिनट सिर्फ़ 2000/महीना हैं** (लगभग 33 घंटे)। 5 चैनल x 24 घंटे x 30 दिन = 3600 घंटे। Private repo में यह नहीं चल सकता।
- **Public repo में मिनट असीमित हैं**, लेकिन GitHub की शर्तें Actions को 24x7 streaming के लिए इस्तेमाल करने की अनुमति नहीं देतीं। अकाउंट/रेपो पर रोक लग सकती है। जोखिम आपका है।
- हर 6 घंटे पर handoff के समय स्ट्रीम में कुछ सेकंड का गैप आ सकता है।
- Facebook live की अपनी अधिकतम अवधि होती है। गैप आने पर Facebook पर नया live video बन सकता है।

## सेटअप
1. **Secrets** (Settings -> Secrets and variables -> Actions -> New repository secret):

   | Secret | मतलब |
   |---|---|
   | `YT_STREAM_KEY_1` ... `YT_STREAM_KEY_5` | 5 YouTube चैनल की stream key |
   | `FB_STREAM_KEY_1` ... `FB_STREAM_KEY_5` | 5 Facebook page की stream key |
   | `YT_COOKIES` (वैकल्पिक) | YouTube वीडियो डाउनलोड block हो तो cookies.txt की पूरी सामग्री |

   जिस चैनल की कोई एक key न हो, वह सिर्फ़ दूसरे platform पर चलेगा।

2. **वीडियो के लिंक** (कितने भी, 5 से ज़्यादा भी): Actions -> **Set Videos** -> Run workflow
   - `channel`: 1 से 5
   - `mode`: `add` (जोड़ें) / `replace` (पूरी लिस्ट बदलें) / `clear` (सब हटाएँ)
   - `links`: YouTube लिंक, कॉमा / space / नई लाइन से अलग करके

   `channels.json` अपने-आप बदलकर commit हो जाती है (चाहें तो उसे हाथ से भी बदल सकते हैं)। नई लिस्ट चल रहे session में नहीं, **अगले session (handoff) से** लागू होती है। तुरंत बदलना हो तो उस चैनल का चल रहा run Cancel करके Live Stream दोबारा चलाएँ। खाली लिस्ट वाला चैनल नहीं चलेगा।

3. **शुरू करना**: Actions -> **Live Stream** -> Run workflow -> `channel = all` (या `1,3`)।
   बाद में Watchdog अपने-आप गिरे हुए चैनल दोबारा उठा देगा।

4. **रोकना**: Variables में `STREAMING_ENABLED = false` रखें और चल रहे runs को Cancel करें।

## ध्यान रखें
- वीडियो पहली बार 720p में तैयार (download + convert) होकर Actions cache में रखी जाती हैं। लिस्ट बदलने पर अपने-आप दोबारा बनती हैं। Cache की सीमा repo पर 10 GB है, इसलिए हर चैनल की वीडियो मिलाकर ज़्यादा लंबी न रखें।
- GitHub के servers से YouTube कई बार डाउनलोड रोक देता है। ऐसे में `YT_COOKIES` डालें, या वीडियो सीधे repo में mp4 के रूप में रखें।
- दूसरों की वीडियो बार-बार लूप करने से YouTube की "reused content" नीति में दिक्कत आ सकती है। अपनी वीडियो इस्तेमाल करें।
- एक ही चैनल का दोहरा run अपने-आप रोक दिया जाता है (एक key पर दो stream नहीं चल सकतीं)।

## "Sign in to confirm you're not a bot" (YouTube download block)
GitHub के servers का IP YouTube अक्सर block कर देता है, तब लिंक से वीडियो डाउनलोड नहीं होती. दो रास्ते:

1. **सीधी mp4 का लिंक (सबसे भरोसेमंद)**: वीडियो अपने कंप्यूटर पर डाउनलोड करके GitHub **Releases** में attach करें (हर फ़ाइल 2 GB तक), और उसका `.../releases/download/.../video.mp4` लिंक Set Videos में डालें. `.mp4/.mov/.mkv/.webm` पर खत्म होने वाले सीधे लिंक सीधे डाउनलोड होते हैं, YouTube की जाँच नहीं लगती.
   (Private repo की Release का लिंक बिना login नहीं खुलता, इसलिए repo public हो या लिंक सार्वजनिक जगह का हो.)
2. **`YT_COOKIES` secret**: browser में YouTube पर login करके "Get cookies.txt LOCALLY" जैसे extension से `youtube.com` की cookies.txt export करें और उसकी पूरी सामग्री `YT_COOKIES` secret में डालें. यह हर बार काम करने की गारंटी नहीं है, cookies समय के साथ खत्म होती हैं, और मुख्य अकाउंट की जगह अलग अकाउंट इस्तेमाल करना बेहतर है.

## फ़ाइलें
- `channels.json` — चैनल और वीडियो की सूची
- `.github/workflows/set-videos.yml` — Actions से लिंक जोड़ने/बदलने का workflow
- `live/live.py` — सारा लॉजिक (plan, prepare, handoff, stream, watchdog)
- `.github/workflows/live-stream.yml` — मुख्य workflow
- `.github/workflows/watchdog.yml` — हर 30 मिनट की जाँच
- `bot.py`, `Dockerfile` — पुराना VPS/Docker वाला तरीका (अब ज़रूरी नहीं)
