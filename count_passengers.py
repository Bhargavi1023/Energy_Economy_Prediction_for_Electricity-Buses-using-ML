# realtime_counter.py
# Real-time webcam passenger counter using YOLOv8
# Counts people crossing door line → pushes to Flask dashboard
#
# HOW TO RUN:
#   1. First start Flask server: python backend/app.py
#   2. Then run this: python yolo_passenger/realtime_counter.py
#   3. Webcam window opens — show people crossing the line
#   4. Press 'q' to quit

import cv2
import requests
import time
from ultralytics import YOLO

# ─── Config ───
FLASK_URL    = "http://127.0.0.1:5000"
DOOR_LINE_Y  = 300      # horizontal line position (pixels from top)
MAX_CAPACITY = 50
TRIP_ID      = None     # will be fetched from Flask
STOP_ID      = 1        # current stop (update manually or via Flask)

# ─── Load YOLOv8 ───
print("Loading YOLOv8...")
model = YOLO('yolov8n.pt')
print("Model loaded! Starting webcam...")

# ─── State ───
total_boarded   = 0
total_alighted  = 0
current_onboard = 0
tracked_ids     = {}    # track_id → last y position
last_push_time  = 0

# ─── Webcam ───
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

if not cap.isOpened():
    print("ERROR: Cannot open webcam!")
    exit()

print("Webcam started!")
print("=" * 50)
print("Instructions:")
print("  - Walk towards camera = BOARD (+1)")
print("  - Walk away from camera = ALIGHT (-1)")
print("  - Press 'q' to quit")
print("=" * 50)

def push_to_flask(boarded_now, alighted_now):
    """Push passenger event to Flask API."""
    try:
        # Get active trip from Flask
        res = requests.get(f"{FLASK_URL}/api/active-trip", timeout=2)
        if res.status_code == 200:
            trip_data = res.json()
            trip_id = trip_data.get('trip_id')
            stop_id = trip_data.get('current_stop_id', 1)
        else:
            trip_id = None
            stop_id = 1

        if trip_id:
            payload = {
                "trip_id" : trip_id,
                "stop_id" : stop_id,
                "boarded" : boarded_now,
                "alighted": alighted_now,
                "detection_source": "yolo_webcam"
            }
            r = requests.post(
                f"{FLASK_URL}/api/passenger-event",
                json=payload, timeout=2
            )
            if r.status_code == 200:
                data = r.json()
                print(f"  → Flask updated: {data['total_onboard']} onboard "
                      f"({data['load_percent']}% load)")
    except Exception as e:
        print(f"  → Flask push skipped: {e}")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Cannot read frame!")
        break

    # ─── YOLOv8 tracking ───
    results = model.track(
        frame,
        persist  = True,
        classes  = [0],      # person only
        conf     = 0.4,
        verbose  = False
    )

    boarded_this_frame  = 0
    alighted_this_frame = 0

    if results[0].boxes.id is not None:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        ids   = results[0].boxes.id.cpu().numpy().astype(int)

        for box, track_id in zip(boxes, ids):
            x1, y1, x2, y2 = map(int, box)
            cy = (y1 + y2) // 2   # center y

            prev_y = tracked_ids.get(track_id)
            if prev_y is not None:
                # Crossing door line downward = BOARD
                if prev_y < DOOR_LINE_Y <= cy:
                    boarded_this_frame  += 1
                    total_boarded       += 1
                    current_onboard      = min(current_onboard+1, MAX_CAPACITY)
                    print(f"[BOARDED]  Total onboard: {current_onboard}")

                # Crossing door line upward = ALIGHT
                elif prev_y > DOOR_LINE_Y >= cy:
                    alighted_this_frame += 1
                    total_alighted      += 1
                    current_onboard      = max(current_onboard-1, 0)
                    print(f"[ALIGHTED] Total onboard: {current_onboard}")

            tracked_ids[track_id] = cy

            # Draw bounding box
            cv2.rectangle(frame, (x1,y1), (x2,y2), (0,255,0), 2)
            cv2.putText(frame, f"ID:{track_id}",
                        (x1, y1-8), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0,255,0), 1)

    # Push to Flask if any crossing happened
    if (boarded_this_frame > 0 or alighted_this_frame > 0):
        push_to_flask(boarded_this_frame, alighted_this_frame)

    # ─── Draw UI on frame ───
    h, w = frame.shape[:2]

    # Door line
    cv2.line(frame, (0, DOOR_LINE_Y), (w, DOOR_LINE_Y), (0,0,255), 2)
    cv2.putText(frame, "DOOR LINE",
                (10, DOOR_LINE_Y-10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)

    # Stats overlay (top-left)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0,0), (280, 110), (0,0,0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    cv2.putText(frame, f"Onboard : {current_onboard}/{MAX_CAPACITY}",
                (10,25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,0), 2)
    cv2.putText(frame, f"Boarded : {total_boarded}",
                (10,50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 1)
    cv2.putText(frame, f"Alighted: {total_alighted}",
                (10,72), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,165,255), 1)

    # Load bar
    load_pct = current_onboard / MAX_CAPACITY
    bar_color = (0,255,0) if load_pct < 0.7 else \
                (0,165,255) if load_pct < 0.9 else (0,0,255)
    cv2.rectangle(frame, (10,82), (10+int(load_pct*200), 96),
                  bar_color, -1)
    cv2.putText(frame, f"Load: {load_pct*100:.0f}%",
                (10,108), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (255,255,255), 1)

    cv2.imshow("YOLOv8 Passenger Counter — Press Q to quit", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

print("\n" + "="*40)
print("SESSION SUMMARY")
print("="*40)
print(f"Total boarded  : {total_boarded}")
print(f"Total alighted : {total_alighted}")
print(f"Final onboard  : {current_onboard}")
print(f"Load           : {current_onboard/MAX_CAPACITY*100:.1f}%")