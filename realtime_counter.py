# realtime_counter.py — FINAL VERSION
# Original door line cross logic (as requested)
# Fixes applied:
#   1. Confidence lowered to 0.20 → detects sitting/dark room persons
#   2. Count persists — does NOT reset when person disappears from frame
#   3. Flask sync fixed — pushes only when count changes
#   4. MJPG codec for stable webcam
#
# HOW IT WORKS:
#   Person walks TOWARDS camera, crosses door line downward → BOARD (+1)
#   Person walks AWAY from camera, crosses door line upward  → ALIGHT (-1)
#   Count stays until next cross event
#
# RUN:
#   Terminal 1: python backend/app.py
#   Terminal 2: python yolo_passenger/realtime_counter.py

import cv2
import requests
import time
import numpy as np
from ultralytics import YOLO

FLASK_URL    = "http://127.0.0.1:5000"
DOOR_LINE_Y  = 300
MAX_CAPACITY = 50
CONF_THRESH  = 0.20   # lowered for better detection in dim light / sitting

print("Loading YOLOv8n...")
model = YOLO('yolov8n.pt')
print("Model loaded!")

# ── State ─────────────────────────────────────────────────────
total_boarded   = 0
total_alighted  = 0
current_onboard = 0
tracked_ids     = {}   # {track_id: last_cy}

# ── Flask trip cache ──────────────────────────────────────────
cached_trip_id  = None
cached_stop_id  = 1
last_trip_check = 0
last_pushed     = -1

def get_active_trip():
    global cached_trip_id, cached_stop_id, last_trip_check
    now = time.time()
    if now - last_trip_check < 3 and cached_trip_id:
        return cached_trip_id, cached_stop_id
    try:
        r = requests.get(f"{FLASK_URL}/api/active-trip", timeout=2)
        if r.status_code == 200:
            d = r.json()
            cached_trip_id = d.get('trip_id')
            cached_stop_id = d.get('current_stop_id', 1)
            last_trip_check = now
    except Exception:
        pass
    return cached_trip_id, cached_stop_id

def push_count(total):
    global last_pushed
    if total == last_pushed:
        return
    trip_id, stop_id = get_active_trip()
    if not trip_id:
        print("  ⚠️  No active trip — start trip on dashboard first")
        return
    try:
        r = requests.post(
            f"{FLASK_URL}/api/set-passenger-count",
            json={"trip_id": trip_id, "stop_id": stop_id, "total_onboard": total},
            timeout=2
        )
        if r.status_code == 200:
            d = r.json()
            last_pushed = total
            print(f"  → Flask ✅  {total} onboard  ({d.get('load_percent',0):.0f}% load)")
        else:
            print(f"  → Flask HTTP {r.status_code}")
    except requests.exceptions.ConnectionError:
        print("  ⚠️  Flask not running")
    except Exception as e:
        print(f"  ⚠️  {e}")

# ── Camera ────────────────────────────────────────────────────
def open_camera():
    for idx, backend in [(0,cv2.CAP_DSHOW),(0,cv2.CAP_ANY),(1,cv2.CAP_DSHOW),(1,cv2.CAP_ANY)]:
        cap = cv2.VideoCapture(idx, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            print(f"✅ Camera opened (index={idx})")
            return cap
    return None

cap = open_camera()
if cap is None:
    print("❌ No webcam found!")
    exit(1)

for _ in range(5):
    cap.read()
    time.sleep(0.05)

print("="*50)
print("  Walk TOWARDS camera  →  BOARD  (+1)")
print("  Walk AWAY from camera →  ALIGHT (-1)")
print("  Press Q to quit")
print("="*50)

fail_count = 0

while True:
    ret, frame = cap.read()
    if not ret or frame is None or frame.size == 0:
        fail_count += 1
        if fail_count > 60:
            break
        time.sleep(0.05)
        continue
    fail_count = 0

    if frame.dtype != np.uint8:
        frame = frame.astype(np.uint8)

    h, w = frame.shape[:2]

    # ── YOLOv8 tracking ──────────────────────────────────────
    results = model.track(
        frame,
        persist = True,
        classes = [0],
        conf    = CONF_THRESH,
        iou     = 0.45,
        verbose = False,
    )

    if results and results[0].boxes is not None and results[0].boxes.id is not None:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        ids   = results[0].boxes.id.cpu().numpy().astype(int)
        confs = results[0].boxes.conf.cpu().numpy()

        for box, tid, conf in zip(boxes, ids, confs):
            x1, y1, x2, y2 = map(int, box)
            cx = (x1+x2)//2
            cy = (y1+y2)//2
            prev_y = tracked_ids.get(tid)

            if prev_y is not None:
                # Downward cross → BOARD
                if prev_y < DOOR_LINE_Y <= cy:
                    total_boarded   += 1
                    current_onboard  = min(current_onboard+1, MAX_CAPACITY)
                    print(f"\n  [BOARDED]  ID:{tid}  Onboard: {current_onboard}")
                    push_count(current_onboard)
                # Upward cross → ALIGHT
                elif prev_y > DOOR_LINE_Y >= cy:
                    total_alighted  += 1
                    current_onboard  = max(current_onboard-1, 0)
                    print(f"\n  [ALIGHTED] ID:{tid}  Onboard: {current_onboard}")
                    push_count(current_onboard)

            tracked_ids[tid] = cy

            # Box colour: green=below line(inside), orange=above(outside)
            color = (0,255,0) if cy > DOOR_LINE_Y else (0,165,255)
            cv2.rectangle(frame, (x1,y1), (x2,y2), color, 2)
            cv2.circle(frame, (cx,cy), 4, (255,255,0), -1)
            cv2.putText(frame, f"ID:{tid} {conf:.2f}",
                        (x1, y1-8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

    # ── Door line ─────────────────────────────────────────────
    cv2.line(frame, (0,DOOR_LINE_Y), (w,DOOR_LINE_Y), (0,0,255), 2)
    cv2.putText(frame, "--- DOOR LINE (cross to count) ---",
                (10, DOOR_LINE_Y-8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,0,255), 2)

    # ── HUD ───────────────────────────────────────────────────
    overlay = frame.copy()
    cv2.rectangle(overlay, (0,0), (330,135), (0,0,0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    cv2.putText(frame, f"Onboard : {current_onboard}/{MAX_CAPACITY}",
                (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,255), 2)
    cv2.putText(frame, f"Boarded : {total_boarded}",
                (10,56), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0,255,0), 1)
    cv2.putText(frame, f"Alighted: {total_alighted}",
                (10,78), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0,165,255), 1)

    pct = current_onboard/MAX_CAPACITY
    bc  = (0,255,0) if pct<0.7 else (0,165,255) if pct<0.9 else (0,0,255)
    cv2.rectangle(frame,(10,92),(10+int(pct*280),108),bc,-1)
    cv2.rectangle(frame,(10,92),(290,108),(100,100,100),1)
    cv2.putText(frame, f"Load: {pct*100:.0f}%",
                (10,126), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,255), 1)

    cv2.imshow("YOLOv8 Passenger Counter — Press Q to quit", frame)
    if cv2.waitKey(1) & 0xFF in (ord('q'), 27):
        break

cap.release()
cv2.destroyAllWindows()

print("\n" + "="*40)
print(f"  Boarded  : {total_boarded}")
print(f"  Alighted : {total_alighted}")
print(f"  Final    : {current_onboard}")
print("="*40)