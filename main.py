import os
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
from linebot.v3.webhooks import MessageEvent, ImageMessageContent

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)
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
    try:
        # 1. ดึงไฟล์รูปจาก LINE
        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            image_bytes = line_bot_blob_api.get_message_content(message_id=event.message.id)

        # 2. ให้ Gemini วิเคราะห์
        pprompt = """
        คุณคือผู้เชี่ยวชาญคำนวณเส้นทางสำหรับคนขับรถส่งของ (ไรเดอร์) ในกรุงเทพฯ และปริมณฑล
        จงอ่านภาพออเดอร์นี้ ระบุจุดรับ (ต้นทาง) และจุดส่ง (ปลายทาง)
        จากนั้นวิเคราะห์เส้นทางขับขี่ด้วยเงื่อนไขที่เข้มงวดที่สุดดังนี้:

        1. บังคับวิ่งเฉพาะ "ถนนพื้นราบสายหลัก" เท่านั้น (ห้ามคิดคำนวณบนทางด่วนเด็ดขาด)
        2. ระบุ "เขต/อำเภอทางผ่าน": ต้องเป็นเขตที่แนวถนนสายหลักพาดผ่านจริง และเบี่ยงเข้าซอยได้ไม่เกิน 1 กิโลเมตรจากถนนเส้นหลักเท่านั้น (ห้ามแนะนำเขตที่ต้องเลี้ยวอ้อมไกลเกิน 1 กม. เด็ดขาด)
        3. ระบุ "เขต/อำเภอปลายทาง"
        4. ระบุ "เขตยืดระยะ": ต้องเป็นเขต/อำเภอที่อยู่ในแนวแกนถนนเส้นเดิม ยืดตรงต่อไปข้างหน้าไม่เกิน 20-30 กิโลเมตร เพื่อรับงานยาวต่อเนื่องได้คุ้มค่า

        ตอบกลับในรูปแบบข้อความกระชับ ตรงไปตรงมา ไม่มีคำทักทายหรือคำเกริ่นนำ ตามรูปแบบนี้:
        📍 เขตทางผ่าน (พื้นราบ ไม่เกิน 1 กม.):
        - ...
        🎯 เขตปลายทาง:
        - ...
        🚀 เขตยืดระยะ (ไปต่อทิศเดิม):
        - ...
        """

        response = client.models.generate_content(
          model='gemini-3.6-flash',
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type='image/jpeg',
                ),
                prompt
            ]
        )

        reply_text = response.text.strip() if response.text else "ขออภัย ไม่สามารถอ่านข้อมูลเส้นทางได้"

        # 3. ตอบกลับ LINE
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
