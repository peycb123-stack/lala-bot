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
from linebot.v3.webhooks import MessageEvent, ImageMessageContent, TextMessageContent

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# สร้างพื้นที่จดจำโหมดของคนขับแต่ละคน (ชั่วคราวก่อนต่อฐานข้อมูลจริง)
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

    # 1. ปุ่มสลับโหมดรถ
    if text == "สลับโหมดรถ":
        current_mode = user_modes.get(user_id, "car")
        if current_mode == "car":
            user_modes[user_id] = "motorcycle"
            reply = "🛵 สลับเป็นโหมด 'มอเตอร์ไซค์' เรียบร้อยครับ\nระบบจะเปิดทางลัดและซอยทะลุให้ในการส่งรูปครั้งต่อไป"
        else:
            user_modes[user_id] = "car"
            reply = "🚗 สลับเป็นโหมด 'รถยนต์' เรียบร้อยครับ\nระบบจะเน้นถนนเมนหลักและซอยกว้างให้ในการส่งรูปครั้งต่อไป"
            
    # 2. ปุ่มเช็คสถานะ
    elif text == "เช็คสถานะ":
        reply = "🟢 สถานะของคุณ: ทดลองใช้งานฟรี\n(ระบบสมาชิกเต็มรูปแบบกำลังจะเปิดให้บริการเร็วๆ นี้)"
        
    # 3. ปุ่มวิธีใช้งาน
    elif text == "วิธีใช้งาน":
        reply = "📌 วิธีใช้งานผู้ช่วยเส้นทาง:\n1. กดเลือก 'โหมดรถ' ด้านล่างให้ตรงกับพาหนะ\n2. แคปหน้าจอออเดอร์ให้เห็นจุดรับ-ส่ง\n3. ส่งรูปเข้ามาในแชทนี้แล้วรอระบบคำนวณ 1-3 วินาที"
        
    # 4. ปุ่มต่ออายุ
    elif text == "ต่ออายุ":
        reply = "💳 ต่ออายุรายเดือน (99 บาท)\n\nโอนเงินเข้าบัญชี:\nธนาคาร: กสิกรไทย\nเลขบัญชี: 123-4-56789-0\nชื่อบัญชี: บจก. ลาล่าบอท\n\nใครโอนแล้วรบกวนส่งสลิปเข้ามาในแชทนี้ได้เลยครับ"
        
    # กรณีพิมพ์ข้อความอื่นเข้ามากวนบอท
    else:
        reply = "หากต้องการวิเคราะห์เส้นทาง กรุณาส่งเป็น 'รูปภาพออเดอร์' เข้ามาได้เลยครับ"

    # ส่งข้อความตอบกลับ
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
        # ตรวจสอบว่าคนขับเลือกโหมดอะไรไว้ (ถ้ายังไม่เคยเลือก ค่าเริ่มต้นคือรถยนต์)
        mode = user_modes.get(user_id, "car")

        if mode == "car":
            vehicle_condition = "พาหนะ: รถยนต์ (เน้นถนนสายหลัก ซอยกว้าง รถไม่ติดขัด ห้ามแนะนำซอยแคบ)"
        else:
            vehicle_condition = "พาหนะ: มอเตอร์ไซค์ (สามารถแนะนำทางลัด ซอยทะลุ หรือเส้นทางหลบรถติดได้)"

        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            image_bytes = line_bot_blob_api.get_message_content(message_id=event.message.id)

        route_prompt = f"""
คุณคือผู้เชี่ยวชาญคำนวณเส้นทางและพื้นที่งานสำหรับคนขับรถส่งของในกรุงเทพฯ และปริมณฑล
ให้วิเคราะห์ภาพที่ได้รับอย่างละเอียด บอทต้องแยกแยะประเภทของภาพและทำงานตามกรณีใดกรณีหนึ่งดังนี้:

**{vehicle_condition}**

🔴 กรณีที่ 1: ถ้าภาพเป็น "หน้าจอออเดอร์งาน (แอป Lalamove)"
จงอ่านข้อความเพื่อระบุจุดรับและจุดส่ง จากนั้นวิเคราะห์เส้นทางด้วยเงื่อนไข:
1. บังคับจำลองเส้นทางบน "ถนนพื้นราบสายหลัก" เท่านั้น (ห้ามคิดคำนวณบนทางด่วนเด็ดขาด)
2. กฎการเลือกเส้นทาง: ให้คิดเหมือนคนขับรถจริง หลีกเลี่ยงการผ่าใจกลางเมือง (CBD เช่น สีลม สยาม) ที่รถติดหนักหากมีถนนเลี่ยงเมืองหรือถนนสายหลักเส้นอื่นที่ทำเวลาได้ดีกว่า และหากต้องข้ามแม่น้ำ ให้ระบุชื่อสะพานที่ใช้
3. ระบุ "แขวง/ตำบลทางผ่าน": โดยให้วงเล็บ (ชื่อถนนสายหลัก หรือ สะพาน ที่ใช้ขับผ่านแขวงนั้นๆ) กำกับไว้ด้านหลังเสมอ เพื่อความชัดเจน และต้องอยู่ในระยะเบี่ยงเบนไม่เกิน 1 กม. จากถนนหลัก
4. ระบุ "แขวง/ตำบลปลายทาง"
5. ระบุ "แขวง/ตำบลยืดระยะ" (พื้นที่หรืออำเภอที่อยู่เลยจุดหมายปลายทางออกไปในทิศทางเดียวกัน 20-30 กม.)

รูปแบบการตอบ (แสดงเฉพาะข้อมูลด้านล่าง ห้ามมีคำเกริ่นนำ):
📍 แขวง/ตำบลทางผ่าน (พื้นราบ ≤ 1 กม.):
- [ชื่อแขวง/ตำบล] ([ชื่อเขต/อำเภอ]) ผ่านเส้น: [ชื่อถนนหลัก/สะพาน]
🎯 ปลายทาง:
- [ชื่อแขวง/ตำบล], [ชื่อเขต/อำเภอ]
🚀 แขวงยืดระยะ (ไปต่อทิศเดิม):
- [ชื่อแขวง/ตำบล] ([ชื่อเขต/อำเภอ])

🔵 กรณีที่ 2: ถ้าภาพเป็น "แอปแผนที่ (เช่น Google Maps)"
ผู้ใช้อยู่ในโหมด "ตีรถเปล่า" และต้องการหาชื่อแขวง/ตำบลเพื่อไปตั้งค่าดักงานทางผ่านในแอป
ให้อ่านเส้นทางนำทาง (เช่น เส้นสีน้ำเงิน) จากภาพ:
1. "สำคัญมาก": แม้เส้นทางสีน้ำเงินในแผนที่จะลากขึ้นทางด่วนหรือโทลล์เวย์ ให้คุณแปลงเป็น "ชื่อแขวง/ตำบลบนถนนพื้นราบ" ที่วิ่งขนานอยู่ใต้แนวด่วนนั้นแทนเสมอ 
2. ไล่เรียงรายชื่อ "แขวง/ตำบล" ทางผ่านทั้งหมดตั้งแต่ต้นจนจบ

รูปแบบการตอบ (แสดงเฉพาะข้อมูลด้านล่าง ห้ามมีคำเกริ่นนำ):
🗺️ เส้นทางตีรถเปล่า (อิงตามแผนที่):
- ต้นทาง: [ชื่อแขวง/เขต] ➡️ ปลายทาง: [ชื่อแขวง/เขต]
📍 แขวง/ตำบลทางผ่าน (สำหรับนำไปตั้งค่ารับงาน):
- [ชื่อแขวง/ตำบล] ([ชื่อเขต/อำเภอ])

⚫ กรณีที่ 3: ภาพไม่เกี่ยวข้องกับออเดอร์ส่งของหรือแผนที่
รูปแบบการตอบ:
❌ ขออภัยครับ ภาพนี้ไม่สามารถวิเคราะห์เส้นทางได้ กรุณาส่งหน้าจอใบงาน หรือรูป Google Maps ครับ
"""

        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type='image/jpeg',
                ),
                route_prompt
            ]
        )

        reply_text = response.text.strip() if response.text else "ขออภัย ไม่สามารถอ่านข้อมูลเส้นทางได้"

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
