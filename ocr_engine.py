import os
import json
import time
from google import genai
from google.genai import types

def extract_order_info(image_bytes, max_retries=3):
    """
    รับภาพใบงานและสกัดข้อมูลจุดรับ-จุดส่งออกมาเป็น JSON
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("ไม่พบ GEMINI_API_KEY ใน Environment Variables")

    client = genai.Client(api_key=api_key)

    prompt = """
    สกัดข้อมูลจุดรับและจุดส่งจากรูปภาพใบงานนี้
    ให้ตอบกลับมาเป็นรูปแบบ JSON เท่านั้น ห้ามมี Markdown (```json) คลุม ห้ามพิมพ์ข้อความอธิบายใดๆ ทั้งสิ้น
    โดยต้องมีโครงสร้างดังนี้เป๊ะๆ:
    {
      "is_order": true หรือ false (ตรวจสอบว่าเป็นใบงานส่งของหรือไม่),
      "pickup": "ชื่อบริษัท/ร้านค้า และที่อยู่จุดรับทั้งหมดรวมกัน",
      "dropoff": "ชื่อบริษัท/ร้านค้า และที่อยู่จุดส่งทั้งหมดรวมกัน"
    }
    ถ้าไม่ใช่ใบงาน ให้ is_order เป็น false และ pickup/dropoff เป็น string ว่าง ""
    """

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                    prompt
                ]
            )
            
            # ทำความสะอาดข้อความ เผื่อ Gemini แอบใส่ฟอร์แมต Markdown มาให้
            clean_text = response.text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
                
            clean_text = clean_text.strip()
            
            # แปลง Text ให้เป็น Python Dictionary (JSON)
            order_data = json.loads(clean_text)
            return order_data
            
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error (Attempt {attempt+1}): {e}")
            if attempt == max_retries - 1:
                raise Exception("AI ไม่สามารถสกัดข้อมูลที่อยู่ได้ในขณะนี้")
                
        except Exception as e:
            error_str = str(e)
            if '503' in error_str or '429' in error_str:
                # ระบบหน่วงเวลาแบบทวีคูณ (1s, 2s, 4s) เพื่อทะลวงคิวเซิร์ฟเวอร์
                time.sleep(2 ** attempt) 
                continue
            raise e
            
    raise Exception("เกิดข้อผิดพลาดในการเชื่อมต่อกับเซิร์ฟเวอร์ AI ครบกำหนดเวลาแล้ว")
