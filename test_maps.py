import googlemaps
from datetime import datetime
import re

# 1. นำ API Key ที่ก็อปปี้มาใส่ตรงนี้
MAPS_API_KEY = "AIzaSyDkOKGBWAJPCh7Wobl9pCAwDB_f5_I5EBM"
gmaps = googlemaps.Client(key=MAPS_API_KEY)

def test_realtime_route(origin_text, destination_text):
    print(f"📍 กำลังประมวลผลเส้นทาง: {origin_text} ➡️ {destination_text}")
    print("-" * 40)
    
    try:
        # 2. ส่งคำขอไป Google Maps พร้อมเงื่อนไข: ขับรถ, เลี่ยงด่วน, และออกเดินทาง "ตอนนี้"
        now = datetime.now()
        directions = gmaps.directions(
            origin=origin_text,
            destination=destination_text,
            mode="driving",
            avoid="tolls", # บังคับเลี่ยงทางด่วน (พื้นราบเท่านั้น)
            departure_time=now, # จุดสำคัญ: ใช้สภาพจราจรแบบเรียลไทม์
            language="th"
        )

        if not directions:
            print("❌ ไม่พบเส้นทาง")
            return

        route = directions[0]['legs'][0]
        distance = route['distance']['text']
        
        # ดึงเวลาแบบรวมสภาพรถติดปัจจุบัน
        duration_in_traffic = route.get('duration_in_traffic', route['duration'])['text'] 
        
        print(f"📏 ระยะทางรวม: {distance}")
        print(f"⏱️ เวลาเดินทาง (รวมรถติด): {duration_in_traffic}")
        print("🗺️ ถนนหลักที่ระบบเลือกใช้เพื่อหลบรถติด:")
        
        # 3. ดึงขั้นตอนการนำทางเพื่อหาชื่อถนน
        passed_roads = []
        for step in route['steps']:
            instructions = step['html_instructions']
            # ลบแท็ก HTML ออกเพื่อให้เหลือแต่ตัวหนังสือ
            clean_text = re.sub('<[^<]+>', '', instructions)
            
            # กรองเอาเฉพาะคำแนะนำที่มีคำว่า ถนน, ซอย หรือ สะพาน
            if any(keyword in clean_text for keyword in ["ถนน", "ซอย", "สะพาน"]):
                # ตัดคำซ้ำซ้อน
                if clean_text not 직 not in passed_roads:
                    passed_roads.append(clean_text)

        for road in passed_roads:
            print(f"   - {road}")

    except Exception as e:
        print(f"เกิดข้อผิดพลาด: {e}")

# ลองรันคำสั่งด้วยพิกัดสมมติ (เสมือนว่า Gemini อ่านข้อความจากรูปมาให้แล้ว)
test_realtime_route(
    origin_text="ซอย ลาดพร้าว 87 วังทองหลาง กรุงเทพ", 
    destination_text="ซอย สมเด็จเจ้าพระยา 7 คลองสาน กรุงเทพ"
)
