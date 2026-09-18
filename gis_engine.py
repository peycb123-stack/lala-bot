import os
import polyline
import geopandas as gpd
from shapely.geometry import Point

# ตำแหน่งไฟล์แผนที่ GeoJSON ที่เราสร้างโฟลเดอร์เผื่อไว้
GEOJSON_PATH = 'data/districts.geojson'

# ตัวแปร Global สำหรับเก็บข้อมูลแผนที่ไว้ใน RAM
gdf = None

def load_gis_data():
    """
    ฟังก์ชันโหลดไฟล์ GeoJSON เข้ามาใน RAM 
    (ทำงานครั้งเดียวตอนเซิร์ฟเวอร์ Start หรือเมื่อถูกเรียก)
    """
    global gdf
    try:
        # ตรวจสอบว่าไฟล์มีอยู่จริง และมีขนาดใหญ่กว่า 10 bytes (ไม่ใช่แค่ {} ที่เราเพิ่งสร้าง)
        if os.path.exists(GEOJSON_PATH) and os.path.getsize(GEOJSON_PATH) > 10:
            print("⏳ กำลังโหลดข้อมูล GIS แผนที่ประเทศไทยลงใน RAM...")
            gdf = gpd.read_file(GEOJSON_PATH)
            
            # สร้าง Spatial Index ให้ค้นหาพิกัดได้ไวระดับเสี้ยววินาที
            gdf.sindex 
            print("✅ โหลดข้อมูล GIS สำเร็จ!")
        else:
            print("⚠️ ยังไม่มีข้อมูลแผนที่จริงใน data/districts.geojson (ระบบจะข้ามการหาเขตไปก่อน)")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการโหลด GIS Data: {e}")

# สั่งให้โหลดข้อมูลทันทีที่ไฟล์นี้ถูก import
load_gis_data()

def get_passed_districts(encoded_polyline):
    """
    รับเส้นทางที่ถูกเข้ารหัส (Polyline) จาก Google Routes
    แล้วนำมาเทียบกับ Polygon แผนที่ว่าวิ่งพาดผ่านเขต/แขวงใดบ้างเรียงตามลำดับ
    """
    if gdf is None or gdf.empty:
        return ["(กรุณานำไฟล์ GeoJSON ของจริงมาใส่ในโฟลเดอร์ data)"]

    # 1. ถอดรหัส Polyline กลับมาเป็นลิสต์พิกัด [(lat, lng), (lat, lng), ...]
    coords = polyline.decode(encoded_polyline)

    # 2. ลดภาระการคำนวณ (Sampling)
    # สมมติเส้นทางมี 1,000 จุด เราไม่จำเป็นต้องเช็คทุกจุด 
    # เราจะสุ่มหยิบมาเช็คแค่ประมาณ 50 จุดตลอดแนวเส้นทาง (ก็เพียงพอและแม่นยำมากแล้ว)
    step = max(1, len(coords) // 50) 
    sampled_coords = coords[::step]
    
    # ดึงจุดปลายทางมาใส่ด้วยเสมอเพื่อความชัวร์
    if coords[-1] not in sampled_coords:
        sampled_coords.append(coords[-1])

    # 3. แปลงพิกัดเป็น Point Object (ระวัง: ระบบ GIS ทั่วไปใช้ X=lng, Y=lat)
    points = [Point(lng, lat) for lat, lng in sampled_coords]

    passed_areas = []

    # 4. วนลูปเช็คทีละจุดว่า "ตกอยู่ใน Polygon (เขต) ไหน" (Point-in-Polygon)
    for pt in points:
        # หา Polygon ที่ครอบคลุมจุดๆ นี้อยู่
        matches = gdf[gdf.contains(pt)]

        if not matches.empty:
            # ดึงข้อมูลแถวแรกที่เจอ
            row = matches.iloc[0]

            # หมายเหตุ: ชื่อคอลัมน์จะขึ้นอยู่กับไฟล์ GeoJSON ที่คุณโหลดมา 
            # เราดักไว้หลายๆ รูปแบบที่เป็นมาตรฐานของข้อมูลแผนที่ไทย (GISTDA/OSM)
            district = row.get('AMP_TH') or row.get('dname') or row.get('AUMPHUR_TH') or row.get('name') or ""
            subdistrict = row.get('TAM_TH') or row.get('sname') or row.get('TAMBON_TH') or ""

            # ทำความสะอาดคำให้สั้นกระชับ
            district = str(district).replace("เขต", "").replace("อำเภอ", "").strip()
            subdistrict = str(subdistrict).replace("แขวง", "").replace("ตำบล", "").strip()

            if district:
                # จัด Format ตามเงื่อนไขของคุณ
                combo = f"เขต {district}"
                if subdistrict:
                    combo += f" (แขวง {subdistrict})"

                # ถ้าเขตนี้ยังไม่ซ้ำกับเขตล่าสุดที่วิ่งผ่าน ให้เพิ่มเข้าไปในลิสต์ (เรียงลำดับ)
                if not passed_areas or passed_areas[-1] != combo:
                    passed_areas.append(combo)

    if not passed_areas:
        return ["ไม่พบพิกัดในพื้นที่แผนที่"]

    return passed_areas
