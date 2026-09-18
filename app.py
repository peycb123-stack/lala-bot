import os
import threading
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, ImageMessageContent, TextMessageContent

# นำเข้า Engine ทั้ง 3 ตัวที่เราเขียนไว้
import ocr_engine
import map_engine
import gis_engine

app = Flask(__name__)

# ดึง API Key จาก Environment (Render)
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# พื้นที่เก็บการตั้งค่าโหมดคนขับ (ชั่วคราวบน RAM)
user_settings = {}

def get_user_setting(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {"mode": "TWO_WHEELER", "avoid_tolls": True}
    return user_settings[user_id]

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 1. จัดการข้อความ Text (เมนูตั้งค่า) ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    setting = get_user_setting(user_id)

    if text == "สลับโหมดรถ":
        if setting["mode"] == "DRIVE":
            setting["mode"] = "TWO_WHEELER"
            reply = "🛵 สลับเป็นโหมด 'มอเตอร์ไซค์' เรียบร้อยครับ"
        else:
            setting["mode"] = "DRIVE"
            reply = "🚗 สลับเป็นโหมด 'รถยนต์' เรียบร้อยครับ"
            
    elif text == "สลับทางด่วน":
        if setting["avoid_tolls"]:
            setting["avoid_tolls"] = False
            reply = "🛣️ โหมดทางด่วน: 'อนุญาตให้ขึ้นทางด่วนได้'"
        else:
            setting["avoid_tolls"] = True
            reply = "🛑 โหมดทางด่วน: 'หลีกเลี่ยงทางด่วน'"

    elif text == "เช็คสถานะ":
        mode_th = "มอเตอร์ไซค์" if setting["mode"] == "TWO_WHEELER" else "รถยนต์"
        toll_th = "เลี่ยง" if setting["avoid_tolls"] else "ขึ้นได้"
        reply = f"🟢 สถานะ: พร้อมใช้งาน\n🚗 โหมดรถ: {mode_th}\n🛣️ ทางด่วน: {toll_th}\n\n(ระบบ V.3: ประหยัดค่าแผนที่ & คำนวณพิกัดภูมิศาสตร์จริง)"
        
    elif text == "วิธีใช้งาน":
        reply = "📌 ส่งรูปหน้าจอออเดอร์ให้เห็นจุดรับ-ส่ง\nระบบจะวิเคราะห์เขต/แขวงที่วิ่งผ่านให้ครับ\nพิมพ์ 'สลับโหมดรถ' หรือ 'สลับทางด่วน' เพื่อตั้งค่า"
        
    else:
        reply = "หากต้องการวิเคราะห์เส้นทาง กรุณาส่งเป็น 'รูปภาพใบงาน' เข้ามาได้เลยครับ"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )

# --- 2. ฟังก์ชันประมวลผลเบื้องหลัง (ไม่ให้ LINE หมดเวลา) ---
def process_order_background(user_id, message_id, settings):
    try:
        # สเตป A: ดึงไฟล์รูปภาพจาก LINE
        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            image_bytes = line_bot_blob_api.get_message_content(message_id=message_id)

        # สเตป B: เรียกใช้ OCR Engine (Gemini -> JSON)
        order_info = ocr_engine.extract_order_info(image_bytes)
        
        if not order_info.get("is_order") or not order_info.get("pickup") or not order_info.get("dropoff"):
            send_push_message(user_id, "❌ รูปภาพไม่ชัดเจนหรือไม่ใช่ใบงานจัดส่งครับ")
            return

        pickup_text = order_info["pickup"]
        dropoff_text = order_info["dropoff"]

        # สเตป C: แปลงที่อยู่เป็นพิกัด (Map Engine -> Geocoding + Cache)
        pickup_coords = map_engine.get_coordinates(pickup_text)
        dropoff_coords = map_engine.get_coordinates(dropoff_text)

        # สเตป D: ขอเส้นทางขับรถ (Map Engine -> Routes API + Cache)
        route_result = map_engine.get_route_polyline(
            pickup_coords, 
            dropoff_coords, 
            mode=settings["mode"], 
            avoid_tolls=settings["avoid_tolls"]
        )

        # สเตป E: หาเขตและแขวง (GIS Engine -> ถอดรหัสพิกัดฟัน Polygon ฟรี)
        passed_districts = gis_engine.get_passed_districts(route_result["polyline"])
        route_text = "\n🔹 ".join(passed_districts)

        # สเตป F: จัดรูปแบบส่งกลับให้คนขับ
        mode_icon = "🛵" if settings["mode"] == "TWO_WHEELER" else "🚗"
        
        # ตัดข้อความจุดรับ-ส่งให้สั้นลง ไม่ให้รกจอเกินไป
        pickup_show = pickup_text[:35] + "..." if len(pickup_text) > 35 else pickup_text
        dropoff_show = dropoff_text[:35] + "..." if len(dropoff_text) > 35 else dropoff_text

        final_reply = (f"🟢 รับ: {pickup_show}\n"
                       f"🔴 ส่ง: {dropoff_show}\n\n"
                       f"{mode_icon} {route_result['distance_km']} กม. | ⏱️ {route_result['duration_mins']} นาที\n\n"
                       f"📍 พื้นที่วิ่งผ่าน:\n🔹 {route_text}")
                       
        send_push_message(user_id, final_reply)

    except Exception as e:
        print(f"Background Process Error: {e}")
        send_push_message(user_id, "❌ ระบบคำนวณเส้นทางขัดข้องชั่วคราว รบกวนส่งรูปใหม่อีกครั้งครับ")

def send_push_message(user_id, text):
    """ส่งข้อความกลับแบบแจ้งเตือน Push Message"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=text)]
            )
        )

# --- 3. จัดการข้อความรูปภาพ (รับรูป -> ตอบแชทรับทราบ -> โยนลง Background) ---
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    user_id = event.source.user_id
    message_id = event.message.id
    
    # ดึงตั้งค่าปัจจุบัน (ก๊อปปี้ค่าไว้เพื่อไม่ให้ Thread ตีกัน)
    setting = get_user_setting(user_id).copy()
    
    # 1. ตอบกลับทันทีภายใน 1-2 วินาที (กันระบบ LINE พัง)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="⏳ รับใบงานแล้ว กำลังวิเคราะห์เส้นทาง...")]
            )
        )
        
    # 2. ปล่อย Thread แบกงานหนักไปคิดเบื้องหลัง
    thread = threading.Thread(target=process_order_background, args=(user_id, message_id, setting))
    thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
