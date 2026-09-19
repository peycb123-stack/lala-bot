import os
import json
import hashlib
import requests
import googlemaps

CACHE_FILE = 'data/cache.json'

def load_cache():
    """โหลดข้อมูล Cache จากไฟล์ (ถ้ามี)"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"geocoding": {}, "routes": {}}
    return {"geocoding": {}, "routes": {}}

def save_cache(cache_data):
    """บันทึกข้อมูลการค้นหาลง Cache เพื่อใช้ซ้ำ"""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Cache Save Error: {e}")

def get_coordinates(address):
    """
    แปลงที่อยู่เป็นพิกัดดาวเทียม (Lat/Lng)
    - ยิงไปหา Google Geocoding
    - บันทึกพิกัดลง Cache
    """
    if not address:
        raise ValueError("ที่อยู่ว่างเปล่า")
        
    cache_data = load_cache()
    
    # ทำความสะอาดข้อความที่อยู่เพื่อใช้เป็นรหัส Key (ป้องกันตัวพิมพ์เล็ก/ใหญ่)
    clean_address = address.strip().lower()
    address_hash = hashlib.md5(clean_address.encode('utf-8')).hexdigest()
    
    # ถ้าเคยหาที่อยู่นี้แล้ว ให้ดึงจาก Cache มาใช้เลย (ฟรี)
    if address_hash in cache_data["geocoding"]:
        return cache_data["geocoding"][address_hash]
        
    api_key = os.environ.get("MAPS_API_KEY")
    if not api_key:
        raise ValueError("ไม่พบ MAPS_API_KEY ใน Environment Variables")
        
    gmaps = googlemaps.Client(key=api_key)
    
    # ยิง API ไปหา Google
    geocode_result = gmaps.geocode(address, region='th', language='th')
    if not geocode_result:
        raise Exception(f"Google Maps ค้นหาพิกัดไม่พบสำหรับที่อยู่: {address[:30]}...")
        
    location = geocode_result[0]['geometry']['location']
    lat_lng = {"lat": location['lat'], "lng": location['lng']}
    
    # เซฟลง Cache ทันที เพื่อประหยัดเงินในอนาคต
    cache_data["geocoding"][address_hash] = lat_lng
    save_cache(cache_data)
    
    return lat_lng

# ถอดพารามิเตอร์ mode และ avoid_tolls ออก เพราะเราจะบังคับค่าตายตัวแล้ว
def get_route_polyline(pickup_latlng, dropoff_latlng):
    """
    ขอเส้นทางและระยะเวลา จาก Google Routes API
    ล็อกโหมด TWO_WHEELER และหลีกเลี่ยงทางด่วนเสมอ
    """
    cache_data = load_cache()
    
    # สร้างรหัส Hash แบบล็อกโหมดมอเตอร์ไซค์
    route_key_raw = f"{pickup_latlng['lat']},{pickup_latlng['lng']}_{dropoff_latlng['lat']},{dropoff_latlng['lng']}_TWO_WHEELER_avoidTolls"
    route_hash = hashlib.md5(route_key_raw.encode('utf-8')).hexdigest()
    
    if route_hash in cache_data["routes"]:
        return cache_data["routes"][route_hash]
        
    api_key = os.environ.get("MAPS_API_KEY")
    routes_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"
    }
    
    payload = {
        "origin": {
            "location": { "latLng": { "latitude": pickup_latlng['lat'], "longitude": pickup_latlng['lng'] } }
        },
        "destination": {
            "location": { "latLng": { "latitude": dropoff_latlng['lat'], "longitude": dropoff_latlng['lng'] } }
        },
        "travelMode": "TWO_WHEELER", # ล็อกเป็นโหมดรถจักรยานยนต์
        "languageCode": "th-TH",
        "routingPreference": "TRAFFIC_AWARE",
        "routeModifiers": {
            "avoidTolls": True # ล็อกการหลีกเลี่ยงทางด่วน
        }
    }
        
    # ใส่ Timeout ป้องกันระบบค้าง (5 วินาทีเชื่อมต่อ, 15 วินาทีรอผลลัพธ์)
    resp = requests.post(routes_url, headers=headers, json=payload, timeout=(5, 15))
    
    if resp.status_code != 200 or not resp.json().get("routes"):
        raise Exception(f"Routes API Error: {resp.text}")
        
    route_info = resp.json()["routes"][0]
    
    # คำนวณระยะทาง (กม.) และเวลา (นาที)
    distance_km = round(route_info.get("distanceMeters", 0) / 1000, 1)
    duration_sec = int(route_info.get("duration", "0s").replace("s", ""))
    duration_mins = round(duration_sec / 60)
    encoded_polyline = route_info["polyline"]["encodedPolyline"]
    
    result = {
        "distance_km": distance_km,
        "duration_mins": duration_mins,
        "polyline": encoded_polyline
    }
    
    # เซฟเส้นทางลง Cache
    cache_data["routes"][route_hash] = result
    save_cache(cache_data)
    
    return result
