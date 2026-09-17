import os
import re
import urllib.parse
from datetime import datetime

import googlemaps
from flask import Flask, request, abort
from google import genai
from google.genai import types
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, ImageMessageContent, TextMessageContent

app = Flask(__name__)

# ดึง API Key อย่างปลอดภัยจากเว็บ Render
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MAPS_API_KEY = os.environ.get("MAPS_API_KEY")

# เชื่อมต่อ Services
client = genai.Client(api_key=GEMINI_API_KEY)
gmaps = googlemaps.Client(key=MAPS_API_KEY)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# สร้างพื้นที่จดจำโหมดของคนขับ (จะถูกรีเซ็ตหาก Render Sleep)
user_modes = {}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 1. ฟังก์ชันรับข้อความ เพื่อสลับโหมด
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id

    if text == "สลับโหมดรถ":
        current_mode = user_modes.get(user_id, "car")
        if current_mode == "car":
            user_modes[user_id] = "motorcycle"
            reply = "🛵 สลับเป็นโหมด 'มอเตอร์ไซค์' เรียบร้อยครับ\nระบบจะเปิดทางลัดและซอยทะลุให้ในการส่งรูปครั้งต่อไป"
        else:
            user_modes[user_id] = "car"
            reply = "🚗 สลับเป็นโหมด 'รถยนต์' เรียบร้อยครับ\nระบบจะเน้นถนนเมนหลักและซอยกว้างให้ในการส่งรูปครั้งต่อไป"
            
    elif text == "เช็คสถานะ":
        reply = "🟢 สถานะของคุณ: ทดลองใช้งานฟรี\n(ระบบสมาชิกเต็มรูปแบบกำลังจะเปิดให้บริการเร็วๆ นี้)"
        
    elif text == "วิธีใช้งาน":
        reply = "📌 วิธีใช้งานผู้ช่วยเส้นทาง:\n1. แคปหน้าจอออเดอร์ให้เห็นจุดรับ-ส่ง\n2. ส่งรูปเข้ามาในแชทนี้แล้วรอระบบคำนวณ 1-3 วินาที\n3. กดปุ่ม 'สลับโหมดรถ' หากต้องการเปลี่ยนประเภทรถ"
        
    elif text == "ต่ออายุ":
        reply = "💳 ต่ออายุรายเดือน (99 บาท)\n\nโอนเงินเข้าบัญชี:\nธนาคาร: กสิกรไทย\nเลขบัญชี: 123-4-56789-0\nชื่อบัญชี: บจก. ลาล่าบอท\n\nใครโอนแล้วรบกวนส่งสลิปเข้ามาในแชทนี้ได้เลยครับ"
        
    else:
        reply = "หากต้องการวิเคราะห์เส้นทาง กรุณาส่งเป็น 'รูปภาพออเดอร์' เข้ามาได้เลยครับ"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )

# 2. ฟังก์ชันรับรูปภาพและดึงโหมดมาใช้คำนวณ
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    try:
        user_id = event.source.user_id
        mode = user_modes.get(user_id, "car")

        # 1. ดึงรูปภาพจาก LINE
        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            image_bytes = line_bot_blob_api.get_message_content(message_id=event.message.id)

        # 2. ส่งรูปให้ Gemini (แนะนำใช้รุ่น 8b เพื่อความเร็วสูงสุด 1-2 วินาที)
        prompt = "สกัดข้อมูลจากรูปภาพออเดอร์นี้ ขอแค่ชื่อสถานที่ 'จุดรับ' และ 'จุดส่ง' คั่นด้วยเครื่องหมาย | เช่น 'ซอยลาดพร้าว 87 | สมเด็จเจ้าพระยา 7' ห้ามพิมพ์ข้อความอธิบายอื่นๆ หากไม่ใช่รูปออเดอร์ให้ตอบว่า 'ไม่ใช่รูปใบงาน'"
        
        response = client.models.generate_content(
            model='gemini-1.5-flash-8b', 
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                prompt
            ]
        )
        
        extracted_text = response.text.strip()
        
        if "ไม่ใช่รูปใบงาน" in extracted_text:
            reply_text = "❌ ขออภัยครับ ภาพนี้ไม่สามารถวิเคราะห์เส้นทางได้ กรุณาส่งหน้าจอใบงานครับ"
        else:
            try:
                origin_text, destination_text = extracted_text.split('|')
                
                # 3. ส่งให้ Google Maps
                now = datetime.now()
                directions = gmaps.directions(
                    origin=origin_text.strip(),
                    destination=destination_text.strip(),
                    mode="driving",
                    avoid="tolls", 
                    departure_time=now,
                    language="th"
                )

                if directions:
                    route = directions[0]['legs'][0]
                    distance = route['distance']['text']
                    duration = route.get('duration_in_traffic', route['duration'])['text']
                    
                    passed_roads = []
                    for step in route['steps']:
                        clean_text = re.sub('<[^<]+>', '', step['html_instructions'])
                        if any(keyword in clean_text for keyword in ["ถนน", "ซอย", "สะพาน"]):
                            if clean_text not in passed_roads:
                                passed_roads.append(f"   - {clean_text}")
                    
                    roads_str = "\n".join(passed_roads)
                    
                    # 4. สร้าง URL ลิงก์สำหรับกดเปิดแอปแผนที่นำทาง
                    origin_url = urllib.parse.quote(origin_text.strip())
                    dest_url = urllib.parse.quote(destination_text.strip())
                    maps_link = f"https://www.google.com/maps/dir/?api=1&origin={origin_url}&destination={dest_url}&dir_action=navigate"

                    # สรุปข้อความตอบกลับ
                    reply_text = (f"📍 รับ: {origin_text.strip()}\n"
                                  f"🎯 ส่ง: {destination_text.strip()}\n"
                                  f"📏 ระยะทาง: {distance}\n"
                                  f"⏱️ เวลา (รวมรถติด): {duration}\n"
                                  f"🗺️ ถนนหลักที่ผ่าน:\n{roads_str}\n\n"
                                  f"🚗 กดเพื่อเริ่มนำทาง:\n{maps_link}")
                else:
                    reply_text = "❌ Google Maps ไม่พบเส้นทางบนพื้นราบ"

            except ValueError:
                reply_text = f"❌ อ่านพิกัดไม่สำเร็จ ข้อมูลที่ได้: {extracted_text}"
            except Exception as e:
                reply_text = f"❌ เกิดข้อผิดพลาดฝั่ง Maps: {e}"

        # 5. ตอบกลับผู้ใช้
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )

    except Exception as e:
        print(f"Error: {e}")
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=f"ระบบขัดข้องชั่วคราว: {str(e)}")]
                )
            )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
