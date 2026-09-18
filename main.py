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

# สร้างพื้นที่จดจำโหมดของคนขับ
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

# 1. ฟังก์ชันรับข้อความตอบกลับเมนูต่างๆ
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id

    if text == "สลับโหมดรถ":
        current_mode = user_modes.get(user_id, "car")
        if current_mode == "car":
            user_modes[user_id] = "motorcycle"
            reply = "🛵 สลับเป็นโหมด 'มอเตอร์ไซค์' เรียบร้อยครับ\nระบบจะหาเส้นทางและเวลาสำหรับมอเตอร์ไซค์ให้ในการส่งรูปครั้งต่อไป"
        else:
            user_modes[user_id] = "car"
            reply = "🚗 สลับเป็นโหมด 'รถยนต์' เรียบร้อยครับ\nระบบจะหาเส้นทางและเวลาสำหรับรถยนต์ให้ในการส่งรูปครั้งต่อไป"
            
    elif text == "เช็คสถานะ":
        reply = "🟢 สถานะของคุณ: ทดลองใช้งานฟรี\n(ระบบสมาชิกเต็มรูปแบบกำลังจะเปิดให้บริการเร็วๆ นี้)"
        
    elif text == "วิธีใช้งาน":
        reply = "📌 วิธีใช้งานผู้ช่วยเส้นทาง:\n1. แคปหน้าจอออเดอร์ให้เห็นจุดรับ-ส่ง\n2. ส่งรูปเข้ามาในแชทนี้แล้วรอระบบคำนวณ 3-5 วินาที\n3. ระบบจะสรุปชื่อเขตที่ขับผ่านเพื่อใช้ดูประกอบการรับงานซ้อน"
        
    elif text == "ต่ออายุ":
        reply = "💳 ต่ออายุรายเดือน (99 บาท)\n\nโอนเงินเข้าบัญชี:\nธนาคาร: กสิกรไทย\nเลขบัญชี: 123-4-56789-0\nชื่อบัญชี: บจก. ลาล่าบอท\n\nใครโอนแล้วรบกวนส่งสลิปเข้ามาในแชทนี้ได้เลยครับ"
        
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

# 2. ฟังก์ชันวิเคราะห์รูปภาพและหาเขตที่ขับผ่าน
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    try:
        user_id = event.source.user_id
        mode = user_modes.get(user_id, "car")

        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            image_bytes = line_bot_blob_api.get_message_content(message_id=event.message.id)
            
        # Gemini เด้งที่ 1: อ่านจุดรับส่งจากภาพ (ปรับคำสั่งให้ตัดชื่อร้าน/บริษัททิ้ง แผนที่จะได้ไม่งง)
        prompt_1 = (
            "สกัดข้อมูลจากรูปภาพออเดอร์นี้ ขอแค่ข้อมูลที่อยู่ 'จุดรับ' และ 'จุดส่ง' คั่นด้วยเครื่องหมาย | "
            "เงื่อนไขสำคัญ: ให้ดึงมาเฉพาะ 'ชื่อถนน, ซอย, แขวง, เขต, จังหวัด' เท่านั้น **ตัดชื่อบริษัท ชื่อร้านค้า ชื่ออาคาร หรือชื่อคนทิ้งไปให้หมด** "
            "เช่น ถ้าในรูปเขียนว่า 'บริษัท เอบีซี จำกัด ซอยลาดพร้าว 87' ให้ตอบแค่ 'ซอยลาดพร้าว 87' "
            "ห้ามพิมพ์ข้อความอธิบายอื่นๆ หากไม่ใช่รูปออเดอร์ให้ตอบว่า 'ไม่ใช่รูปใบงาน'"
        )
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
            reply_text = "❌ ขออภัยครับ ภาพนี้ไม่สามารถวิเคราะห์เส้นทางได้ กรุณาส่งหน้าจอใบงานครับ"
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
                    
                    # สกัดเฉพาะข้อความเส้นทาง (ลบ HTML ทิ้ง)
                    step_texts = [re.sub('<[^<]+>', '', step['html_instructions']) for step in route['steps']]
                    full_route_text = ", ".join(step_texts)
                    
                    # Gemini เด้งที่ 2: จัดกลุ่มและดึงเฉพาะแขวง/เขตที่เส้นสีน้ำเงินพาดผ่านเท่านั้น
                    prompt_2 = (f"จากเส้นทางนี้: {full_route_text}\n"
                                "จงดึงเฉพาะชื่อ 'เขต/อำเภอ' และ 'แขวง/ตำบล' ที่เส้นทางนี้ 'ขับพาดผ่านโดยตรงจริงๆ' เท่านั้น ห้ามเดาหรือรวมเขตที่อยู่ไกลออกไปเด็ดขาด\n"
                                "จัดรูปแบบใหม่อ่านง่ายที่สุดตามเงื่อนไขนี้:\n"
                                "1. นำ แขวง/ตำบล ที่อยู่ใน เขต/อำเภอ เดียวกัน มารวมไว้บรรทัดเดียวกันคั่นด้วยลูกน้ำ\n"
                                "2. ขึ้นบรรทัดใหม่เมื่อเปลี่ยน เขต/อำเภอ โดยใช้สัญลักษณ์ 🔹 นำหน้า\n"
                                "3. เรียงลำดับจากจุดเริ่มต้นไปปลายทาง\n"
                                "ตัวอย่างรูปแบบที่ต้องการเป๊ะๆ:\n"
                                "🔹 อ.ธัญบุรี : ต.บึงยี่โถ, ต.ประชาธิปัตย์\n"
                                "🔹 เขตตลิ่งชัน : แขวงตลิ่งชัน, แขวงบางเชือกหนัง\n"
                                "ห้ามมีข้อความเกริ่นนำหรือสรุปใดๆ นอกเหนือจากลิสต์นี้เด็ดขาด")
                    
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

                    # จัด Layout ข้อความใหม่ให้มีพื้นที่ว่างพักสายตา
                    reply_text = (f"🟢 รับ: {origin_text.strip()}\n"
                                  f"🔴 ส่ง: {destination_text.strip()}\n\n"
                                  f"⏱️ ระยะทาง: {distance}\n"
                                  f"⏳ เวลา: {duration}\n\n"
                                  f"📍 พื้นที่วิ่งผ่าน:\n{passed_districts}")
                else:
                    reply_text = "❌ ไม่พบเส้นทาง"

            except ValueError:
                reply_text = f"❌ อ่านพิกัดไม่สำเร็จ ข้อมูลที่ได้: {extracted_text}"
            except Exception as e:
                reply_text = f"❌ เกิดข้อผิดพลาดฝั่ง Maps: {e}"

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
