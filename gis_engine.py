import os
import json
import polyline
import geopandas as gpd
from shapely.geometry import Point, LineString

GEOJSON_PATH = 'data/districts.geojson'
gdf = None

def load_gis_data():
    global gdf
    try:
        if os.path.exists(GEOJSON_PATH) and os.path.getsize(GEOJSON_PATH) > 10:
            print("⏳ กำลังโหลดข้อมูล GIS แผนที่ประเทศไทยลงใน RAM...")
            
            # บายพาส fiona โดยใช้ json อ่านไฟล์ตรงๆ
            with open(GEOJSON_PATH, 'r', encoding='utf-8') as f:
                geo_data = json.load(f)
            
            # แปลงเป็น GeoDataFrame อย่างปลอดภัย
            gdf = gpd.GeoDataFrame.from_features(geo_data['features'])
            gdf.set_crs(epsg=4326, inplace=True) # กำหนดพิกัดโลกมาตรฐาน (สำคัญมาก)
            
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
        coords = polyline.decode(encoded_polyline)
        if len(coords) < 2:
            return ["ไม่พบเส้นทางที่ชัดเจน"]
            
        line = LineString([(lng, lat) for lat, lng in coords])

        possible_matches_index = list(gdf.sindex.intersection(line.bounds))
        possible_matches = gdf.iloc[possible_matches_index]

        precise_matches = possible_matches[possible_matches.intersects(line)]

        if precise_matches.empty:
            return ["ไม่พบพิกัดในพื้นที่แผนที่"]

        intersected_areas = []
        for idx, row in precise_matches.iterrows():
            geom = row.geometry
            intersection = geom.intersection(line)
            dist = line.project(intersection)
            intersected_areas.append((dist, row))

        intersected_areas.sort(key=lambda x: x[0])

        passed_areas = []
        for dist, row in intersected_areas:
            district_raw = row.get('ADM2_TH') or ""
            subdistrict_raw = row.get('ADM3_TH') or ""

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
