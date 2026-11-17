"""
KN IB HUB – Auto Poster
Lấy tin tức Mỹ (Trading / XAUUSD / Vàng / Bitcoin / Fed) từ RSS,
viết lại bằng tiếng Việt, tạo ảnh thương hiệu và đăng lên Facebook Page.

Chạy:  python main.py            -> đăng thật
       DRY_RUN=1 python main.py  -> chỉ tạo ảnh + caption vào thư mục output/, không đăng
"""
import os, re, json, html, time, random, hashlib, datetime as dt
from pathlib import Path

import feedparser
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ======================= CẤU HÌNH =======================
FB_PAGE_ID       = os.getenv("FB_PAGE_ID", "")
FB_PAGE_TOKEN    = os.getenv("FB_PAGE_TOKEN", "")
ANTHROPIC_KEY    = os.getenv("ANTHROPIC_API_KEY", "")      # không bắt buộc (có thì caption hay hơn)
ANTHROPIC_MODEL  = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
POSTS_PER_RUN    = int(os.getenv("POSTS_PER_RUN", "1"))    # 2 lần chạy/ngày x 1 bài = 2 bài/ngày
MAX_AGE_HOURS    = int(os.getenv("MAX_AGE_HOURS", "12"))   # chỉ lấy tin mới trong X giờ
DRY_RUN          = os.getenv("DRY_RUN", "0") == "1"
BRAND            = os.getenv("BRAND", "KN IB HUB")
HASHTAGS         = os.getenv("HASHTAGS", "#KNIBHub #thitruong")
GRAPH_VERSION    = os.getenv("GRAPH_VERSION", "v27.0")

ROOT     = Path(__file__).parent
STATE    = ROOT / "posted.json"
OUT_DIR  = ROOT / "output"
FONT_DIR = ROOT / "fonts"

# Nguồn tin Mỹ (RSS công khai)
FEEDS = {
    "FXStreet":      "https://www.fxstreet.com/rss/news",
    "CNBC":          "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "MarketWatch":   "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "Investing.com": "https://www.investing.com/rss/news_11.rss",
    "CoinDesk":      "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
}

# Từ khóa -> chủ đề (ưu tiên từ trên xuống)
TOPICS = [
    ("VÀNG",    ["gold", "xau", "xauusd", "bullion", "precious metal", "silver"]),
    ("BITCOIN", ["bitcoin", "btc", "crypto", "ethereum", "etf flows", "stablecoin"]),
    ("VĨ MÔ",   ["fed", "fomc", "powell", "cpi", "inflation", "nonfarm", "nfp", "payroll",
                 "treasury", "yield", "rate cut", "rate hike", "pce", "gdp", "jobless"]),
    ("FOREX",   ["usd", "dollar", "eur/usd", "gbp/usd", "usd/jpy", "aud/usd", "dxy", "forex"]),
    ("CHỨNG KHOÁN", ["s&p 500", "nasdaq", "dow jones", "wall street", "stocks"]),
]
UP_WORDS   = ["rise", "rises", "rally", "surge", "jump", "gain", "climb", "record", "high", "soar", "rebound", "above"]
DOWN_WORDS = ["fall", "falls", "drop", "slide", "slump", "plunge", "decline", "lower", "low", "tumble", "below", "sink"]

# ======================= TIỆN ÍCH =======================
def log(*a): print(f"[{dt.datetime.now():%H:%M:%S}]", *a, flush=True)

def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"posted": []}

def save_state(s):
    s["posted"] = s["posted"][-500:]
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()

def uid(link, title):
    return hashlib.md5((link or title).encode()).hexdigest()

def detect_topic(text):
    t = text.lower()
    for name, kws in TOPICS:
        if any(re.search(r"\b" + re.escape(k) + r"\b", t) for k in kws):
            return name
    return None

def detect_direction(text):
    t = text.lower()
    up = sum(bool(re.search(r"\b" + w + r"\b", t)) for w in UP_WORDS)
    dn = sum(bool(re.search(r"\b" + w + r"\b", t)) for w in DOWN_WORDS)
    return "up" if up > dn else "down" if dn > up else "neutral"

# ======================= 1. LẤY TIN =======================
def fetch_news():
    items, now = [], time.time()
    for source, url in FEEDS.items():
        try:
            feed = feedparser.parse(url, agent="Mozilla/5.0 (KN-AutoPost)")
        except Exception as e:
            log("Lỗi feed", source, e); continue
        for e in feed.entries[:40]:
            title = clean(e.get("title"))
            summary = clean(e.get("summary") or e.get("description"))[:600]
            ts = e.get("published_parsed") or e.get("updated_parsed")
            age_h = (now - time.mktime(ts)) / 3600 if ts else 0
            if age_h > MAX_AGE_HOURS:
                continue
            topic = detect_topic(title + " " + summary)
            if not topic:
                continue
            items.append(dict(id=uid(e.get("link"), title), source=source, title=title,
                              summary=summary, link=e.get("link", ""), topic=topic, age_h=age_h))
        log(f"{source}: ok")
    return items

def pick(items, state, n):
    done = set(state["posted"])
    fresh = [i for i in items if i["id"] not in done]
    # ưu tiên Vàng & Bitcoin, sau đó tin mới nhất; mỗi lượt cố gắng khác chủ đề
    prio = {"VÀNG": 0, "BITCOIN": 1, "VĨ MÔ": 2, "FOREX": 3, "CHỨNG KHOÁN": 4}
    recent_topics = state.get("last_topics", [])
    fresh.sort(key=lambda i: (i["topic"] in recent_topics, prio.get(i["topic"], 9), i["age_h"]))
    chosen, used = [], set()
    for it in fresh:
        if it["topic"] in used and len(fresh) > n:
            continue
        chosen.append(it); used.add(it["topic"])
        if len(chosen) == n: break
    return chosen

# ======================= 2. VIẾT LẠI TIẾNG VIỆT =======================
PROMPT = """Bạn là biên tập viên tin tài chính của fanpage "{brand}".
Dựa trên tin tiếng Anh dưới đây, viết lại NGẮN GỌN bằng tiếng Việt (tự diễn đạt, không dịch nguyên văn dài).
Trả về DUY NHẤT JSON:
{{
 "headline": "tiêu đề tiếng Việt <= 70 ký tự, giữ số liệu (vd: Vàng vượt 2.700 USD khi USD suy yếu)",
 "highlight": "1 cụm từ ngắn trong headline để tô màu vàng (vd: vượt 2.700 USD)",
 "subtitle": "1 câu phụ <= 60 ký tự",
 "body": "2-3 câu tóm tắt ý chính và tác động tới thị trường, khách quan",
 "direction": "up | down | neutral (hướng của tài sản chính trong tin)"
}}
Chủ đề: {topic}
Nguồn: {source}
Tiêu đề: {title}
Tóm tắt: {summary}"""

def rewrite_with_claude(it):
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
        "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": ANTHROPIC_MODEL, "max_tokens": 600,
              "messages": [{"role": "user", "content": PROMPT.format(brand=BRAND, **it)}]})
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    return json.loads(re.search(r"\{.*\}", txt, re.S).group(0))

def translate_free(text):
    """Dịch miễn phí qua Google Translate (không cần key)."""
    try:
        r = requests.get("https://translate.googleapis.com/translate_a/single", timeout=20,
                         params={"client": "gtx", "sl": "en", "tl": "vi", "dt": "t", "q": text})
        return "".join(p[0] for p in r.json()[0])
    except Exception:
        return text

def rewrite(it):
    if ANTHROPIC_KEY:
        try:
            return rewrite_with_claude(it)
        except Exception as e:
            log("Claude lỗi, dùng dịch miễn phí:", e)
    head = translate_free(it["title"])
    body = translate_free(it["summary"][:400]) if it["summary"] else ""
    nums = re.findall(r"[\d.,]+\s?(?:USD|\$|%)?", head)
    return {"headline": head, "highlight": nums[0].strip() if nums else "",
            "subtitle": f"Cập nhật thị trường {it['topic'].lower()}",
            "body": body, "direction": detect_direction(it["title"])}

# ======================= 3. TẠO ẢNH =======================
W, H = 1080, 1350
GOLD, GOLD_DARK, WHITE, GREY = (232, 196, 92), (120, 98, 45), (245, 245, 245), (190, 190, 190)

def font(weight, size):
    names = {"black": ["BeVietnamPro-ExtraBold.ttf", "DejaVuSans-Bold.ttf"],
             "bold":  ["BeVietnamPro-Bold.ttf", "DejaVuSans-Bold.ttf"],
             "med":   ["BeVietnamPro-Medium.ttf", "DejaVuSans.ttf"],
             "reg":   ["BeVietnamPro-Regular.ttf", "DejaVuSans.ttf"],
             "serif": ["PlayfairDisplay-Bold.ttf", "DejaVuSerif-Bold.ttf"]}[weight]
    for n in names:
        for d in (FONT_DIR, Path("/usr/share/fonts/truetype/dejavu")):
            if (d / n).exists():
                return ImageFont.truetype(str(d / n), size)
    return ImageFont.load_default()

def wrap(draw, text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= maxw: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

def draw_coin(img, cx, cy, r, symbol, base=(84, 180, 135)):
    d = ImageDraw.Draw(img)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((cx-r+6, cy-r+14, cx+r+6, cy+r+14), fill=(0, 0, 0, 140))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=base)
    lighter = tuple(min(255, c+30) for c in base)
    d.ellipse((cx-r*0.82, cy-r*0.82, cx+r*0.82, cy+r*0.82), outline=lighter, width=max(3, r//18))
    f = font("black", int(r*1.05 if len(symbol) == 1 else r*0.8))
    d.text((cx, cy), symbol, font=f, fill="white", anchor="mm")

def draw_arrow_badge(img, cx, cy, r, direction):
    d = ImageDraw.Draw(img)
    color = (214, 64, 58) if direction == "down" else (46, 170, 100)
    d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=color)
    s = r * 0.5
    if direction == "down":
        d.line((cx, cy-s, cx, cy+s*0.7), fill="white", width=int(r*0.22))
        d.polygon([(cx-s*0.75, cy+s*0.05), (cx+s*0.75, cy+s*0.05), (cx, cy+s*0.95)], fill="white")
    else:
        d.line((cx, cy+s, cx, cy-s*0.7), fill="white", width=int(r*0.22))
        d.polygon([(cx-s*0.75, cy-s*0.05), (cx+s*0.75, cy-s*0.05), (cx, cy-s*0.95)], fill="white")

def make_image(it, vi, path):
    img = Image.new("RGBA", (W, H), (10, 10, 10, 255))
    # nền gradient ánh vàng
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-300, -300, 700, 600), fill=(90, 70, 25, 110))
    gd.ellipse((600, 900, 1500, 1700), fill=(70, 55, 20, 90))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(160)))
    d = ImageDraw.Draw(img)

    # khung viền
    d.rounded_rectangle((55, 55, W-55, H-55), radius=48, outline=GOLD_DARK, width=3)

    # logo
    fl = font("serif", 40)
    kn = BRAND.split()[0]; rest = " ".join(BRAND.split()[1:])
    kw = d.textlength(kn, font=fl)
    d.rectangle((115, 112, 115+kw+28, 168), outline=GOLD, width=3)
    d.text((129, 140), kn, font=fl, fill=GOLD, anchor="lm")
    d.text((115+kw+52, 140), rest, font=fl, fill=GOLD, anchor="lm")

    # nhãn chủ đề
    ft = font("black", 30)
    tw = d.textlength(it["topic"], font=ft)
    d.rounded_rectangle((W-115-tw-56, 108, W-115, 172), radius=32, fill=GOLD)
    d.text((W-115-(tw+56)/2, 140), it["topic"], font=ft, fill=(25, 25, 25), anchor="mm")

    # khu minh họa
    d.rounded_rectangle((120, 205, W-120, 640), radius=36, fill=(22, 22, 22), outline=(70, 60, 35), width=2)
    sym, col = {"VÀNG": ("Au", (205, 160, 50)), "BITCOIN": ("₿", (240, 147, 26)),
                "CHỨNG KHOÁN": ("%", (70, 130, 220))}.get(it["topic"], ("$", (84, 180, 135)))
    if sym == "₿" and "BeVietnam" not in font("black", 10).path:
        sym = "B"
    draw_coin(img, 315, 455, 60, sym, col)
    draw_coin(img, 800, 460, 54, sym, col)
    draw_coin(img, W//2, 425, 140, sym, col)
    if vi.get("direction") in ("up", "down"):
        draw_arrow_badge(img, 860, 300, 54, vi["direction"])
    d = ImageDraw.Draw(img)

    # tiêu đề
    head = vi["headline"].upper()
    hl = (vi.get("highlight") or "").upper()
    size = 76
    while True:
        fh = font("black", size)
        lines = wrap(d, head, fh, W-260)
        if len(lines) <= 4 or size <= 52: break
        size -= 4
    hl_words = set(hl.split())
    y = 1060 - len(lines) * (size + 14)
    y = max(y, 700)
    for line in lines:
        x = 130
        for w in line.split():
            d.text((x, y), w, font=fh, fill=GOLD if w in hl_words else WHITE)
            x += d.textlength(w + " ", font=fh)
        y += size + 14

    # dòng phụ
    fs = font("med", 36)
    for line in wrap(d, vi.get("subtitle", ""), fs, W-260)[:2]:
        y += 18
        d.text((130, y), line, font=fs, fill=GREY); y += 36

    # footer
    d.line((130, 1175, W-130, 1175), fill=(80, 70, 40), width=2)
    f1, f2 = font("reg", 26), font("bold", 26)
    d.text((130, 1210), "Nguồn: ", font=f1, fill=GREY)
    d.text((130 + d.textlength("Nguồn: ", font=f1), 1210), it["source"], font=f2, fill=GOLD)
    d.text((130, 1250), "CFD/Forex rủi ro cao. Không phải lời khuyên đầu tư.", font=font("reg", 22), fill=(150, 150, 150))
    d.text((W-130, 1245), BRAND, font=font("black", 28), fill=GOLD, anchor="rm")

    img.convert("RGB").save(path, quality=95)
    return path

# ======================= 4. ĐĂNG FACEBOOK =======================
def build_caption(it, vi):
    tag = {"VÀNG": "#vang #XAUUSD", "BITCOIN": "#bitcoin #crypto", "VĨ MÔ": "#vimo #Fed",
           "FOREX": "#forex", "CHỨNG KHOÁN": "#chungkhoanmy"}.get(it["topic"], "")
    return (f"{vi['headline']}\n\n{vi.get('body', '')}\n\n"
            f"Theo {it['source']}.\n"
            f"⚠️ Giao dịch CFD/Forex có rủi ro cao. Đây không phải lời khuyên đầu tư.\n"
            f"{HASHTAGS} {tag}").strip()

def post_to_facebook(image_path, caption):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{FB_PAGE_ID}/photos"
    with open(image_path, "rb") as f:
        r = requests.post(url, timeout=120, data={"caption": caption, "access_token": FB_PAGE_TOKEN},
                          files={"source": f})
    if r.status_code != 200:
        raise RuntimeError(f"Facebook lỗi {r.status_code}: {r.text}")
    return r.json()

# ======================= MAIN =======================
def main():
    if not DRY_RUN and not (FB_PAGE_ID and FB_PAGE_TOKEN):
        raise SystemExit("Thiếu FB_PAGE_ID / FB_PAGE_TOKEN (hoặc chạy DRY_RUN=1 để thử).")
    OUT_DIR.mkdir(exist_ok=True)
    state = load_state()
    items = fetch_news()
    log(f"Tìm được {len(items)} tin phù hợp")
    chosen = pick(items, state, POSTS_PER_RUN)
    if not chosen:
        log("Không có tin mới để đăng."); return
    topics = []
    for it in chosen:
        log(f"→ [{it['topic']}] {it['title']} ({it['source']})")
        vi = rewrite(it)
        img = make_image(it, vi, OUT_DIR / f"{it['id']}.jpg")
        cap = build_caption(it, vi)
        (OUT_DIR / f"{it['id']}.txt").write_text(cap, encoding="utf-8")
        if DRY_RUN:
            log("DRY_RUN – đã tạo", img)
        else:
            res = post_to_facebook(img, cap)
            log("Đã đăng:", res)
        state["posted"].append(it["id"]); topics.append(it["topic"])
        time.sleep(random.randint(5, 15))
    state["last_topics"] = topics
    if not DRY_RUN:
        save_state(state)

if __name__ == "__main__":
    main()
