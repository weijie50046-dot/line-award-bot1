import os
import io
import json
import random
import math
from flask import Flask, request, abort, send_from_directory
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
    ImageMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai

app = Flask(__name__)

# ==================== 金鑰設定區 ====================
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "c2d47c13a69c2cacf8d8bce060fb0eb2")
CHANNEL_ACCESS_TOKEN = os.getenv(
    "LINE_CHANNEL_ACCESS_TOKEN",
    "jW9ZnLhPmV07TlBAuY5BxH3gypcaFQS8cZNbez1TvyF4h/4RtLiPzhz8feL3iTOvyJ4ewZaJsi8sEZF6KoncbykZsYMLKn8v3/RypIC3N/LLzfxJ8tFDlgjmvtDTZ4/eSX/S9ziE8yOtfk7rXJayOgdB04t89/1O/w1cDnyilFU="
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6JalZyfUj5EKQ_vqu647mVTQPoxczDNnCLDf6XC9zUvTw")
# ===================================================

genai.configure(api_key=GEMINI_API_KEY)
handler = WebhookHandler(CHANNEL_SECRET)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

# 暫存每個使用者的最新狀態：包含文案、最後上傳的照片、最近一次使用的風格
user_sessions = {}

def get_font(size):
    """取得中文字型，優先載入專案目錄下的 font.ttf"""
    font_paths = [
        "font.ttf",                         # 專案根目錄下的思源黑體
        "fonts/font.ttf",                   # fonts 資料夾
        "fonts/GenSenRounded-B.ttc",        # 自訂字型
        "C:/Windows/Fonts/msjhbd.ttc",       # 本機微軟正黑體
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

def ask_ai_to_expand_copy(user_input: str) -> dict:
    """利用 AI 將使用者輸入擴充為正式表揚文案與多樣化精神標語"""
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""
    你是郵局行銷美工與激勵專家。使用者輸入了得獎同仁的簡短資訊：
    "{user_input}"

    請幫忙整理並優化成表揚海報的 4 個區塊文案：
    1. title: 主標題/獎項名稱（如「局長MVP獎」、「月度業績達標獎」、「週週達標 犒賞有感」）
    2. subtitle: 激勵或門檻副標（如「單日月保收達標・犒賞有感」、「各局達標喝飲料・人人有單」）
    3. unit: 單位與得獎人（如「恭喜！中苗郵局 神隊友：姿儀」）
    4. slogan: 底部精神標語，請根據主題動態發想，有氣勢、活潑或押韻（約 12~18 字，前後加上 ★）

    請務必只回傳純 JSON 格式：
    {{
      "title": "局長MVP獎",
      "subtitle": "單日月保收達標 犒賞有感",
      "unit": "恭喜！中苗郵局 神隊友：姿儀",
      "slogan": "★ 局局進件人人有單・榮耀加冕實至名歸 ★"
    }}
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception:
        backup_slogans = [
            "★ 週週達標・局局進件・人人有單 ★",
            "★ 業績滾滾來・榮耀加冕創佳績 ★",
            "★ 熱血出擊・勢不可擋・神隊友太強啦 ★",
            "★ 達標有感・喝飲料犒賞・人人開紅盤 ★"
        ]
        return {
            "title": "榮耀達標獎",
            "subtitle": "達標有成・人人有單",
            "unit": user_input,
            "slogan": random.choice(backup_slogans)
        }

def draw_banner_text(draw, xy, text, font, fill_color, stroke_color=(0, 0, 0), stroke_width=5):
    """繪製立體描邊字"""
    x, y = xy
    for dx in range(-stroke_width - 2, stroke_width + 3):
        for dy in range(-stroke_width - 2, stroke_width + 3):
            draw.text((x + dx + 3, y + dy + 4), text, font=font, fill=(15, 15, 15))
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            draw.text((x + dx, y + dy), text, font=font, fill=stroke_color)
    draw.text((x, y), text, font=font, fill=fill_color)

def crop_and_fit_photo(photo: Image.Image, target_w=640, target_h=480) -> Image.Image:
    """自動縮放裁切照片至相框比例"""
    photo = photo.convert("RGB")
    photo_ratio = photo.width / photo.height
    target_ratio = target_w / target_h
    if photo_ratio > target_ratio:
        new_h = target_h
        new_w = int(target_h * photo_ratio)
    else:
        new_w = target_w
        new_h = int(target_w / photo_ratio)
    photo = photo.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return photo.crop((left, top, left + target_w, top + target_h))

def render_confetti(draw, canvas_w, canvas_h, colors):
    """灑滿彩帶碎紙花"""
    for _ in range(85):
        cx = random.randint(10, canvas_w - 10)
        cy = random.randint(10, canvas_h - 10)
        if 260 < cy < 740 and 100 < cx < 700:
            continue
        size = random.randint(8, 16)
        c = random.choice(colors)
        if random.random() > 0.5:
            draw.rectangle([cx, cy, cx + size, cy + size // 2], fill=c)
        else:
            draw.polygon([(cx, cy), (cx + size, cy + size // 2), (cx + size // 2, cy + size)], fill=c)

# ==================== 4 種風格繪製引擎 ====================
def render_style_green_mvp(canvas, draw, photo_cropped, copy_data, font_t, font_s, font_u):
    """風格 1：翡翠金綠 MVP"""
    canvas_w, canvas_h = 800, 1100
    # 放射光芒
    center_x, center_y = canvas_w // 2, 200
    for angle in range(0, 360, 15):
        r1, r2 = math.radians(angle), math.radians(angle + 7)
        draw.polygon([(center_x, center_y),
                      (center_x + int(1200 * math.cos(r1)), center_y + int(1200 * math.sin(r1))),
                      (center_x + int(1200 * math.cos(r2)), center_y + int(1200 * math.sin(r2)))],
                     fill=(12, 85, 48))
    render_confetti(draw, canvas_w, canvas_h, [(255, 215, 0), (255, 80, 80), (80, 180, 255), (255, 255, 255)])
    
    # 拍立得照片框
    draw.rectangle([70, 254, 738, 758], fill=(0, 20, 10))
    draw.rectangle([66, 246, 734, 754], fill=(255, 255, 255))
    canvas.paste(photo_cropped, (80, 260))

    # 金色大牌匾
    draw.rectangle([50, 45, 750, 150], fill=(180, 130, 20), outline=(255, 230, 120), width=4)
    draw.rectangle([55, 50, 745, 145], fill=(230, 175, 30))
    tw = draw.textbbox((0, 0), copy_data["title"], font=font_t)[2] - draw.textbbox((0, 0), copy_data["title"], font=font_t)[0]
    draw_banner_text(draw, ((canvas_w - tw)//2, 62), copy_data["title"], font_t, (255, 255, 255), (120, 40, 10), 5)

    # 副標與名單
    draw.rounded_rectangle([160, 170, 640, 225], radius=12, fill=(210, 40, 40), outline=(255, 230, 120), width=3)
    sw = draw.textbbox((0, 0), copy_data["subtitle"], font=font_s)[2] - draw.textbbox((0, 0), copy_data["subtitle"], font=font_s)[0]
    draw.text(((canvas_w - sw)//2, 180), copy_data["subtitle"], font=font_s, fill=(255, 255, 255))

    draw.rounded_rectangle([50, 800, 750, 890], radius=16, fill=(245, 245, 245), outline=(210, 40, 40), width=4)
    uw = draw.textbbox((0, 0), copy_data["unit"], font=font_u)[2] - draw.textbbox((0, 0), copy_data["unit"], font=font_u)[0]
    draw.text(((canvas_w - uw)//2, 818), copy_data["unit"], font=font_u, fill=(200, 20, 20))

def render_style_baseball(canvas, draw, photo_cropped, copy_data, font_t, font_s, font_u):
    """風格 2：熱血棒球運動"""
    canvas_w, canvas_h = 800, 1100
    # 海軍藍與運動跑道線條
    for y in range(0, canvas_h, 30):
        draw.line([(0, y), (canvas_w, y)], fill=(18, 32, 70), width=2)
    
    # 棒球運動雙外框 (紅藍霓虹框)
    draw.rectangle([66, 246, 734, 754], fill=(220, 40, 40))
    draw.rectangle([72, 252, 728, 748], fill=(255, 255, 255))
    canvas.paste(photo_cropped, (80, 260))

    # 火焰冠軍標題牌
    draw.rounded_rectangle([40, 40, 760, 155], radius=20, fill=(20, 40, 100), outline=(255, 60, 40), width=5)
    tw = draw.textbbox((0, 0), copy_data["title"], font=font_t)[2] - draw.textbbox((0, 0), copy_data["title"], font=font_t)[0]
    draw_banner_text(draw, ((canvas_w - tw)//2, 60), copy_data["title"], font_t, (255, 220, 50), (180, 20, 20), 6)

    # 副標與名單
    draw.rectangle([140, 175, 660, 225], fill=(240, 150, 20))
    sw = draw.textbbox((0, 0), copy_data["subtitle"], font=font_s)[2] - draw.textbbox((0, 0), copy_data["subtitle"], font=font_s)[0]
    draw.text(((canvas_w - sw)//2, 182), copy_data["subtitle"], font=font_s, fill=(255, 255, 255))

    draw.rounded_rectangle([50, 800, 750, 890], radius=16, fill=(255, 240, 200), outline=(20, 40, 100), width=4)
    uw = draw.textbbox((0, 0), copy_data["unit"], font=font_u)[2] - draw.textbbox((0, 0), copy_data["unit"], font=font_u)[0]
    draw_banner_text(draw, ((canvas_w - uw)//2, 815), copy_data["unit"], font_u, (210, 30, 30), (255, 255, 255), 3)

def render_style_celebration_red(canvas, draw, photo_cropped, copy_data, font_t, font_s, font_u):
    """風格 3：喜慶紅金達標"""
    canvas_w, canvas_h = 800, 1100
    render_confetti(draw, canvas_w, canvas_h, [(255, 215, 0), (255, 240, 150), (255, 255, 255)])
    
    # 金色豪華厚相框
    draw.rectangle([66, 246, 734, 754], fill=(230, 180, 50))
    draw.rectangle([74, 254, 726, 746], fill=(255, 255, 255))
    canvas.paste(photo_cropped, (80, 260))

    # 大紅燈籠牌匾
    draw.rounded_rectangle([50, 45, 750, 150], radius=30, fill=(190, 20, 20), outline=(255, 220, 80), width=4)
    tw = draw.textbbox((0, 0), copy_data["title"], font=font_t)[2] - draw.textbbox((0, 0), copy_data["title"], font=font_t)[0]
    draw_banner_text(draw, ((canvas_w - tw)//2, 62), copy_data["title"], font_t, (255, 230, 80), (60, 0, 0), 5)

    draw.rounded_rectangle([150, 170, 650, 225], radius=12, fill=(255, 245, 200), outline=(190, 20, 20), width=2)
    sw = draw.textbbox((0, 0), copy_data["subtitle"], font=font_s)[2] - draw.textbbox((0, 0), copy_data["subtitle"], font=font_s)[0]
    draw.text(((canvas_w - sw)//2, 180), copy_data["subtitle"], font=font_s, fill=(180, 20, 20))

    draw.rounded_rectangle([50, 800, 750, 890], radius=16, fill=(255, 255, 255), outline=(230, 180, 50), width=4)
    uw = draw.textbbox((0, 0), copy_data["unit"], font=font_u)[2] - draw.textbbox((0, 0), copy_data["unit"], font=font_u)[0]
    draw.text(((canvas_w - uw)//2, 818), copy_data["unit"], font=font_u, fill=(190, 20, 20))

def render_style_block_party(canvas, draw, photo_cropped, copy_data, font_t, font_s, font_u):
    """風格 4：繽紛派對積木"""
    canvas_w, canvas_h = 800, 1100
    # 頂部彩色三角旗
    flag_colors = [(230, 50, 50), (50, 150, 230), (250, 200, 30), (50, 180, 80), (230, 100, 30)]
    for i in range(10):
        fx = i * 80
        draw.polygon([(fx, 0), (fx + 80, 0), (fx + 40, 45)], fill=flag_colors[i % len(flag_colors)])

    # 彩色積木拼色框
    draw.rectangle([66, 246, 734, 754], fill=(240, 180, 30))
    draw.rectangle([74, 254, 726, 746], fill=(255, 255, 255))
    canvas.paste(photo_cropped, (80, 260))

    # 派對積木泡泡標題
    draw.rounded_rectangle([50, 60, 750, 160], radius=25, fill=(255, 255, 255), outline=(230, 50, 50), width=5)
    tw = draw.textbbox((0, 0), copy_data["title"], font=font_t)[2] - draw.textbbox((0, 0), copy_data["title"], font=font_t)[0]
    draw_banner_text(draw, ((canvas_w - tw)//2, 75), copy_data["title"], font_t, (230, 50, 50), (50, 50, 50), 4)

    draw.rounded_rectangle([150, 175, 650, 230], radius=15, fill=(50, 150, 230))
    sw = draw.textbbox((0, 0), copy_data["subtitle"], font=font_s)[2] - draw.textbbox((0, 0), copy_data["subtitle"], font=font_s)[0]
    draw.text(((canvas_w - sw)//2, 185), copy_data["subtitle"], font=font_s, fill=(255, 255, 255))

    draw.rounded_rectangle([50, 800, 750, 890], radius=16, fill=(255, 255, 255), outline=(50, 180, 80), width=4)
    uw = draw.textbbox((0, 0), copy_data["unit"], font=font_u)[2] - draw.textbbox((0, 0), copy_data["unit"], font=font_u)[0]
    draw.text(((canvas_w - uw)//2, 818), copy_data["unit"], font=font_u, fill=(20, 100, 200))

# ==================== 主合成排版入口 ====================
STYLE_CONFIGS = {
    "green_mvp": {"bg": (6, 56, 32), "fn": render_style_green_mvp, "name": "榮耀金綠 MVP 風格"},
    "baseball": {"bg": (10, 20, 50), "fn": render_style_baseball, "name": "熱血棒球賽事風格"},
    "red_gold": {"bg": (130, 15, 15), "fn": render_style_celebration_red, "name": "喜慶紅金達標風格"},
    "party_block": {"bg": (250, 245, 235), "fn": render_style_block_party, "name": "繽紛派對積木風格"}
}

def create_award_poster(photo: Image.Image, copy_data: dict, selected_style: str = None) -> tuple[str, str]:
    """合成海報主函式：支援隨機挑選或指定風格"""
    canvas_w, canvas_h = 800, 1100
    
    # 決定風格
    if not selected_style or selected_style not in STYLE_CONFIGS:
        selected_style = random.choice(list(STYLE_CONFIGS.keys()))
    
    cfg = STYLE_CONFIGS[selected_style]
    canvas = Image.new("RGB", (canvas_w, canvas_h), color=cfg["bg"])
    draw = ImageDraw.Draw(canvas)

    font_t = get_font(60)
    font_s = get_font(30)
    font_u = get_font(42)

    # 裁切照片並套用該風格繪製
    photo_cropped = crop_and_fit_photo(photo, target_w=640, target_h=480)
    cfg["fn"](canvas, draw, photo_cropped, copy_data, font_t, font_s, font_u)

    # 底部精神標語
    slogan = copy_data.get("slogan", "★ 達標有感・人人有單・再創佳績 ★")
    sw = draw.textbbox((0, 0), slogan, font=font_s)[2] - draw.textbbox((0, 0), slogan, font=font_s)[0]
    s_x = (canvas_w - sw) // 2
    draw_banner_text(draw, (s_x, 930), slogan, font_s, (255, 220, 60), (0, 0, 0), 3)

    # 疊加自訂裝飾貼紙（若存在）
    sticker_path = "assets/sticker_cheer.png"
    if os.path.exists(sticker_path):
        try:
            st = Image.open(sticker_path).convert("RGBA").resize((170, 170))
            canvas.paste(st, (590, 750), st)
        except Exception:
            pass

    # 輸出圖檔
    os.makedirs("static", exist_ok=True)
    out_name = f"award_{os.urandom(4).hex()}.jpg"
    canvas.save(os.path.join("static", out_name), format="JPEG", quality=95)
    return out_name, cfg["name"]

# ==================== Web 伺服器與 LINE 接收 ====================
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    user_id = event.source.user_id
    user_input = event.message.text.strip()

    # 檢查是否為「重新生成 / 換一張 / 指定風格」指令
    regen_keywords = ["換一張", "重做", "重抽", "重產", "重新生成", "不喜歡", "再一張", "換風格"]
    is_regen = any(k in user_input for k in regen_keywords)
    
    style_aliases = {
        "棒球": "baseball",
        "金綠": "green_mvp", "mvp": "green_mvp", "綠色": "green_mvp",
        "紅金": "red_gold", "紅色": "red_gold", "喜慶": "red_gold",
        "積木": "party_block", "派對": "party_block"
    }
    matched_style = None
    for kw, s_key in style_aliases.items():
        if kw in user_input.lower():
            matched_style = s_key
            break

    # 執行重新生成邏輯
    if (is_regen or matched_style) and user_id in user_sessions and "photo" in user_sessions[user_id]:
        session = user_sessions[user_id]
        # 若沒指定風格，自動避開上一次的風格挑選新風格
        if not matched_style:
            avail_styles = [k for k in STYLE_CONFIGS.keys() if k != session.get("last_style")]
            matched_style = random.choice(avail_styles)
        
        session["last_style"] = matched_style
        saved_filename, style_title = create_award_poster(session["photo"], session["copy"], matched_style)

        base_url = request.host_url.rstrip("/").replace("http://", "https://")
        img_url = f"{base_url}/static/{saved_filename}"

        reply_tip = (
            f"🎨 已為您換上【{style_title}】！\n\n"
            f"💡 若想再嘗試其他風格：\n"
            f"・輸入「換一張」隨機換色\n"
            f"・指定「換棒球風」、「換金綠風」、「換紅金風」或「換積木風」"
        )
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        ImageMessage(original_content_url=img_url, preview_image_url=img_url),
                        TextMessage(text=reply_tip)
                    ]
                )
            )
        return

    # 一般文字設定：透過 AI 擴充文案
    expanded = ask_ai_to_expand_copy(user_input)
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    user_sessions[user_id]["copy"] = expanded

    reply_content = (
        f"✅ 已為您生成表揚文案：\n"
        f"─────────────────\n"
        f"🏆 獎項：{expanded['title']}\n"
        f"🎯 門檻：{expanded['subtitle']}\n"
        f"👏 名單：{expanded['unit']}\n"
        f"📣 標語：{expanded.get('slogan', '')}\n"
        f"─────────────────\n"
        f"📷 請直接傳送「得獎同仁照片」，馬上為您隨機合成一種風格的海報！"
    )

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_content)])
        )

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    user_id = event.source.user_id

    if user_id not in user_sessions or "copy" not in user_sessions[user_id]:
        msg = "💡 請先傳送文字設定局所與獎項喔！\n\n例如直接輸入：\n中苗郵局 姿儀 局長MVP獎"
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=msg)])
            )
        return

    # 下載傳送的照片並在 session 暫存
    with ApiClient(configuration) as api_client:
        blob_api = MessagingApiBlob(api_client)
        img_bytes = blob_api.get_message_content(message_id=event.message.id)
        user_photo = Image.open(io.BytesIO(img_bytes))
        
        user_sessions[user_id]["photo"] = user_photo

        # 隨機挑選風格合成海報
        chosen_style = random.choice(list(STYLE_CONFIGS.keys()))
        user_sessions[user_id]["last_style"] = chosen_style

        saved_filename, style_title = create_award_poster(user_photo, user_sessions[user_id]["copy"], chosen_style)

        base_url = request.host_url.rstrip("/").replace("http://", "https://")
        image_url = f"{base_url}/static/{saved_filename}"

        reply_tip = (
            f"🎉【{style_title}】已生成！\n\n"
            f"👉 若想換其他樣式，直接回覆：\n"
            f"「換一張」或是指定「換棒球風」、「換積木風」、「換金綠風」！"
        )
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    ImageMessage(original_content_url=image_url, preview_image_url=image_url),
                    TextMessage(text=reply_tip)
                ]
            )
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
