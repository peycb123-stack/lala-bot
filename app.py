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

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 1. จัดการข้อความ Text (เมนูวิธีใช้งาน) ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    text = event.message.text.strip()

    if text == "วิธีใช้งาน":
        reply = (
            "🛵 ระบบวิเคราะห์เส้นทางรับ-ส่ง (โหมดมอเตอร์ไซค์)\n\n"
            "ส่งรูปภาพหน้างานของคุณเข้ามาได้เลย ระบบจะคำนวณเส้นทางให้โดย:\n"
            "✅ อ้างอิงเส้นทางรถจักรยานยนต์\n"
            "✅ หลีกเลี่ยงทางด่วนเป็นหลัก\n\n"
            "📍 ระบบจะแสดงรายชื่อ เขต/แขวง ที่เส้นทางพาดผ่าน เพื่อให้คุณประเมินหางานพ่วงและเส้นทางขากลับได้ง่ายขึ้นครับ"
        )
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
def process_order_background(user_id, message_id):
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

        # สเตป D: ขอเส้นทางขับรถ (ส่งแค่จุดรับ-ส่ง เพราะล็อกโหมดรถและเลี่ยงทางด่วนใน map_engine แล้ว)
        route_result = map_engine.get_route_polyline(pickup_coords, dropoff_coords)

        # สเตป E: หาเขตและแขวง (GIS Engine -> ถอดรหัสพิกัดฟัน Polygon ฟรี)
        passed_districts = gis_engine.get_passed_districts(route_result["polyline"])
        route_text = "\n🔹 ".join(passed_districts)

        # สเตป F: จัดรูปแบบส่งกลับให้คนขับ
        pickup_show = pickup_text[:35] + "..." if len(pickup_text) > 35 else pickup_text
        dropoff_show = dropoff_text[:35] + "..." if len(dropoff_text) > 35 else dropoff_text

        final_reply = (f"🟢 รับ: {pickup_show}\n"
                       f"🔴 ส่ง: {dropoff_show}\n\n"
                       f"🛵 {route_result['distance_km']} กม. | ⏱️ {route_result['duration_mins']} นาที\n"
                       f"🛑 เส้นทาง: หลีกเลี่ยงทางด่วน\n\n"
                       f"📍 พื้นที่วิ่งผ่าน:\n🔹 {route_text}\n\n"
                       f"💡 ส่งงานถัดไปมาได้เลยครับ")
                       
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
    
    # 1. ตอบกลับทันทีภายใน 1-2 วินาที (กันระบบ LINE พัง)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="⏳ รับใบงานแล้ว กำลังวิเคราะห์เส้นทาง...")]
            )
        )
        
    # 2. ปล่อย Thread แบกงานหนักไปคิดเบื้องหลัง (ไม่ต้องส่ง parameters เรื่องโหมดรถแล้ว)
    thread = threading.Thread(target=process_order_background, args=(user_id, message_id))
    thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
