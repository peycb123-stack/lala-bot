import os
import polyline
import geopandas as gpd
from shapely.geometry import Point

GEOJSON_PATH = 'data/districts.geojson'
gdf = None

def load_gis_data():
    global gdf
    try:
        if os.path.exists(GEOJSON_PATH) and os.path.getsize(GEOJSON_PATH) > 10:
            print("⏳ กำลังโหลดข้อมูล GIS แผนที่ประเทศไทยลงใน RAM...")
            gdf = gpd.read_file(GEOJSON_PATH)
            gdf.sindex 
            print("✅ โหลดข้อมูล GIS สำเร็จ!")
        else:
            print("⚠️ ยังไม่มีข้อมูลแผนที่จริงใน data/districts.geojson")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการโหลด GIS Data: {e}")

load_gis_data()

def get_passed_districts(encoded_polyline):
    if gdf is None or gdf.empty:
        return ["(ยังไม่ได้ใส่ไฟล์ GeoJSON ของจริง)"]

    coords = polyline.decode(encoded_polyline)
    step = max(1, len(coords) // 50) 
    sampled_coords = coords[::step]
    
    if coords[-1] not in sampled_coords:
        sampled_coords.append(coords[-1])

    # แปลงพิกัดเป็น Point Object (ลบบรรทัดที่มี Error ออกแล้ว)
    points = [Point(lng, lat) for lat, lng in sampled_coords]

    passed_areas = []

    for pt in points:
        matches = gdf[gdf.geometry.contains(pt)]

        if not matches.empty:
            row = matches.iloc[0]

            # ดึงชื่อภาษาไทยจากโครงสร้างไฟล์ใหม่ (ADM2_TH = อำเภอ/เขต, ADM3_TH = ตำบล/แขวง)
            district_raw = row.get('ADM2_TH') or ""
            subdistrict_raw = row.get('ADM3_TH') or ""

            # ทำความสะอาดคำให้สั้นกระชับ (เพิ่มการตัด "กิ่งอำเภอ" เพื่อความเนียน)
            district = str(district_raw).replace("กิ่งอำเภอ", "").replace("เขต", "").replace("อำเภอ", "").strip()
            subdistrict = str(subdistrict_raw).replace("แขวง", "").replace("ตำบล", "").strip()

            if district:
                combo = f"เขต {district}"
                if subdistrict:
                    combo += f" (แขวง {subdistrict})"

                if not passed_areas or passed_areas[-1] != combo:
                    if combo not in passed_areas:
                        passed_areas.append(combo)

    if not passed_areas:
        return ["ไม่พบพิกัดในพื้นที่แผนที่"]

    return passed_areas
