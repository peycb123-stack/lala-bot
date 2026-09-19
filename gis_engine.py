import os
import polyline
import geopandas as gpd
from shapely.geometry import LineString

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

    try:
        # 1. ถอดรหัส polyline เป็นพิกัดและสลับเป็น (lng, lat) ให้ตรงตามหลัก GIS
        coords = polyline.decode(encoded_polyline)
        if len(coords) < 2:
            return ["ไม่พบเส้นทางที่ชัดเจน"]
            
        line = LineString([(lng, lat) for lat, lng in coords])

        # 2. ใช้ Spatial Index หากล่อง (Bounding Box) ที่เส้นทางพาดผ่านเพื่อลดภาระการคำนวณ
        possible_matches_index = list(gdf.sindex.intersection(line.bounds))
        possible_matches = gdf.iloc[possible_matches_index]

        # 3. หาเฉพาะเขตที่เส้นตัดผ่านจริงๆ (Intersects)
        precise_matches = possible_matches[possible_matches.intersects(line)]

        if precise_matches.empty:
            return ["ไม่พบพิกัดในพื้นที่แผนที่"]

        # 4. คำนวณระยะทางบนเส้นเพื่อเรียงลำดับเขตตามการวิ่งจริง (จุดรับ -> จุดส่ง)
        intersected_areas = []
        for idx, row in precise_matches.iterrows():
            geom = row.geometry
            intersection = geom.intersection(line)
            # หาว่าจุดที่ตัดเข้าเขตนี้ อยู่ห่างจากจุดเริ่มต้นเส้นทางแค่ไหน
            dist = line.project(intersection)
            intersected_areas.append((dist, row))

        # เรียงลำดับจากระยะทางน้อยไปมาก
        intersected_areas.sort(key=lambda x: x[0])

        # 5. จัดรูปแบบข้อความ
        passed_areas = []
        for dist, row in intersected_areas:
            district_raw = row.get('ADM2_TH') or ""
            subdistrict_raw = row.get('ADM3_TH') or ""

            # ทำความสะอาดคำ
            district = str(district_raw).replace("กิ่งอำเภอ", "").replace("เขต", "").replace("อำเภอ", "").strip()
            subdistrict = str(subdistrict_raw).replace("แขวง", "").replace("ตำบล", "").strip()

            if district:
                combo = f"เขต {district}"
                if subdistrict:
                    combo += f" (แขวง {subdistrict})"

                if not passed_areas or passed_areas[-1] != combo:
                    if combo not in passed_areas:
                        passed_areas.append(combo)

        return passed_areas

    except Exception as e:
        print(f"❌ GIS Processing Error: {e}")
        return ["เกิดข้อผิดพลาดในการวิเคราะห์พื้นที่"]
