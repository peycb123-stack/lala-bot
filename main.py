import os
import json
from flask import Flask, request, abort
import google.generativeai as genai
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
from linebot.v3.webhooks import MessageEvent, ImageMessageContent

app = Flask(__name__)

# ดึงค่าจาก Environment Variables
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
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

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    # 1. ดึงภาพจาก LINE
    with ApiClient(configuration) as api_client:
        line_bot_blob_api = MessagingApiBlob(api_client)
        image_content = line_bot_blob_api.get_message_content(message_id=event.message.id)

    # 2. ส่งภาพให้ Gemini วิเคราะห์เส้นทางพื้นราบและยืดระยะ
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = """
    คุณคือผู้ช่วยคำนวณเส้นทางสำหรับคนขับรถส่งของในกรุงเทพฯ และปริมณฑล
    จงอ่านภาพออเดอร์นี้ ระบุจุดรับ (ต้นทาง) และจุดส่ง (ปลายทาง)
    จากนั้นวิเคราะห์เส้นทางขับขี่ด้วยเงื่อนไขสำคัญต่อไปนี้:
    1. บังคับวิ่งเฉพาะ "ถนนพื้นราบ" เท่านั้น (ห้ามคิดคำนวณบนทางด่วนเด็ดขาด)
    2. ระบุ "เขต/อำเภอทางผ่าน" ในระยะเบี่ยงเบนไม่เกิน 1-2 กิโลเมตรจากถนนเส้นหลัก
    3. ระบุ "เขต/อำเภอปลายทาง"
    4. ระบุ "เขตยืดระยะ" คือพื้นที่หรืออำเภอ/เขตที่อยู่เลยจุดหมายปลายทางออกไปในทิศทางเดียวกันและคุ้มค่าที่จะรับงานต่อเนื่อง

    ตอบกลับในรูปแบบข้อความกระชับ ตรงไปตรงมา ไม่มีคำทักทายหรือคำเกริ่นนำ ตามรูปแบบนี้:
    📍 เขตทางผ่าน (พื้นราบ):
    - ...
    🎯 เขตปลายทาง:
    - ...
    🚀 เขตยืดระยะ (ไปต่อทิศเดิม):
    - ...
    """
    
    response = model.generate_content([
        {'mime_type': 'image/jpeg', 'data': image_content},
        prompt
    ])

    # 3. ตอบข้อความกลับไปยังผู้ใช้ใน LINE
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=response.text.strip())]
            )
        )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
