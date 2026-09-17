import os
import re
import time
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

# ดึง API Key
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MAPS_API_KEY = os.environ.get("MAPS_API_KEY")

# เชื่อมต่อ Services
client = genai.Client(api_key=GEMINI_API_KEY)
gmaps = googlemaps.Client(key=MAPS_API_KEY)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

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

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id

    if text == "สลับโหมดรถ":
        current_mode = user_modes.get(user_id, "car")
        if current_mode == "car":
            user_modes[user_id] = "motorcycle"
            reply = "🛵 โหมด: มอเตอร์ไซค์"
        else:
            user_modes[user_id] = "car"
            reply = "🚗 โหมด: รถยนต์"
    elif text == "เช็คสถานะ":
        reply = "🟢 สถานะ: พร้อมใช้งาน"
    elif text == "วิธีใช้งาน":
        reply = "ส่งรูปใบงานเพื่อดูแนวแขวง/เขต"
    else:
        reply = "ส่งรูปใบงานเข้ามาได้เลยครับ"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    try:
        user_id = event.source.user_id
        mode = user_modes.get(user_id, "car")

        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            image_bytes = line_bot_blob_api.get_message_content(message_id=event.message.id)

        # Gemini เด้งที่ 1: อ่านจุดรับส่งจากภาพ
        prompt_1 = "สกัดข้อมูลจากรูปภาพออเดอร์นี้ ขอแค่ชื่อสถานที่ 'จุดรับ' และ 'จุดส่ง' คั่นด้วยเครื่องหมาย | เช่น 'ซอยลาดพร้าว 87 | สมเด็จเจ้าพระยา 7' ห้ามพิมพ์ข้อความอธิบายอื่นๆ หากไม่ใช่รูปออเดอร์ให้ตอบว่า 'ไม่ใช่รูปใบงาน'"
        
        max_retries = 3
        retry_delay = 2
        response_1 = None
        
        for attempt in range(max_retries):
            try:
                response_1 = client.models.generate_content(
                    model='gemini-3.1-flash-lite', 
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                        prompt_1
                    ]
                )
                break
            except Exception as e:
                if '503' in str(e) or '429' in str(e):
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                raise e

        extracted_text = response_1.text.strip()
        
        if "ไม่ใช่รูปใบงาน" in extracted_text:
            reply_text = "❌ กรุณาส่งรูปใบงาน"
        else:
            try:
                origin_text, destination_text = extracted_text.split('|')
                gmaps_mode = "driving" if mode == "car" else "two_wheeler"
                
                # ขอเส้นทางจาก Google Maps
                now = datetime.now()
                directions = gmaps.directions(
                    origin=origin_text.strip(),
                    destination=destination_text.strip(),
                    mode=gmaps_mode,
                    avoid="tolls", 
                    departure_time=now,
                    language="th"
                )

                if directions:
                    route = directions[0]['legs'][0]
                    distance = route['distance']['text']
                    duration = route.get('duration_in_traffic', route['duration'])['text']
                    
                    # สกัดเฉพาะข้อความเส้นทาง (ลบ HTML ทิ้ง) เพื่อส่งให้ Gemini
                    step_texts = [re.sub('<[^<]+>', '', step['html_instructions']) for step in route['steps']]
                    full_route_text = ", ".join(step_texts)
                    
                    # Gemini เด้งที่ 2: แปลงเส้นทางถนนเป็น เขต/แขวง
                    prompt_2 = (f"นี่คือคำแนะนำเส้นทางขับรถ: {full_route_text}\n"
                                "จงแปลงเส้นทางนี้เป็นชื่อ 'แขวง/เขต' หรือ 'ตำบล/อำเภอ' ที่ขับผ่านหรืออยู่ในรัศมี 1 กม. "
                                "เรียงลำดับจากต้นทางไปปลายทาง ตอบให้สั้นที่สุดแบบนี้: แขวงA > เขตB > ตำบลC "
                                "ห้ามพิมพ์คำอธิบายหรือคำเกริ่นนำใดๆ เด็ดขาด")
                    
                    response_2 = None
                    for attempt in range(max_retries):
                        try:
                            response_2 = client.models.generate_content(
                                model='gemini-3.1-flash-lite', 
                                contents=prompt_2
                            )
                            break
                        except Exception as e:
                            if '503' in str(e) or '429' in str(e):
                                if attempt < max_retries - 1:
                                    time.sleep(retry_delay)
                                    continue
                            raise e
                            
                    passed_districts = response_2.text.strip() if response_2 else "ไม่สามารถระบุเขตได้"

                    # สรุปข้อความตอบกลับแบบสั้นตาแตก
                    reply_text = (f"🟢 รับ: {origin_text.strip()}\n"
                                  f"🔴 ส่ง: {destination_text.strip()}\n"
                                  f"⏱️ {distance} | {duration}\n"
                                  f"📍 ผ่าน: {passed_districts}")
                else:
                    reply_text = "❌ ไม่พบเส้นทาง"

            except ValueError:
                reply_text = f"❌ อ่านพิกัดไม่สำเร็จ: {extracted_text}"
            except Exception as e:
                reply_text = f"❌ Error ฝั่ง Maps: {e}"

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )

    except Exception as e:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=f"ระบบขัดข้อง: {str(e)}")]
                )
            )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
