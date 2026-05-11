# app.py — Smart Electric Bus Flask Backend

from flask import Flask, request, jsonify, render_template
import mysql.connector
import joblib
import pandas as pd
import math
import os

app = Flask(__name__, template_folder='../templates')

def get_db():
    return mysql.connector.connect(
        host="localhost", user="root",
        password="route", database="smart_bus_db"
    )

MODEL_PATH   = os.path.join(os.path.dirname(__file__), '../ml_model/saved_model/energy_model.pkl')
ENCODER_PATH = os.path.join(os.path.dirname(__file__), '../ml_model/saved_model/label_encoder.pkl')
model   = joblib.load(MODEL_PATH)
encoder = joblib.load(ENCODER_PATH)
print("ML Model loaded!")

active_trip    = {"trip_id": None, "current_stop_id": 1}
live_pax_count = {"count": 0}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(d_lon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

def get_smart_stations(lat, lon, kwh_per_km, battery_remaining_kwh, km_remaining):
    db  = get_db()
    cur = db.cursor(dictionary=True)
    # ✅ CHANGED: latitude > 10 (Tirupati lat=13.6)
    cur.execute("SELECT * FROM charging_stations WHERE is_available=1 AND latitude > 10")
    stations = cur.fetchall()
    db.close()
    result = []
    for s in stations:
        dist         = haversine(lat, lon, s['latitude'], s['longitude'])
        energy_reach = dist * kwh_per_km
        energy_total = (km_remaining * kwh_per_km) + energy_reach
        can_reach    = battery_remaining_kwh >= energy_reach
        can_finish   = battery_remaining_kwh >= energy_total
        est_min      = round((dist / 30) * 60)
        if can_finish:
            rec, status = "Complete route then charge", "safe"
        elif can_reach:
            rec, status = "Head to station now — skip remaining stops", "warning"
        else:
            rec, status = "CRITICAL — Cannot reach this station!", "critical"
        result.append({
            'id': s['id'], 'name': s['name'],
            'latitude': s['latitude'], 'longitude': s['longitude'],
            'distance_km': round(dist, 2),
            'energy_to_reach_kwh': round(energy_reach, 2),
            'energy_after_route_kwh': round(energy_total, 2),
            'can_reach_station': can_reach,
            'can_finish_then_charge': can_finish,
            'charger_type': s.get('charger_type', ''),
            'power_kw': s.get('power_kw', 0),
            'recommendation': rec, 'status': status,
            'est_minutes': est_min,
        })
    result.sort(key=lambda x: x['distance_km'])
    return result[:3]

def analyze_battery(battery_pct, battery_capacity, route_stops,
                    avg_speed, ac_on, ambient_temp, traffic_level):
    battery_kwh     = battery_capacity * battery_pct / 100
    base_kwh_per_km = 1.2

    temp_factor = 0.0
    ac_kwh_per_km = 0.0
    if ac_on:
        if ambient_temp <= 22:   temp_factor = 0.3
        elif ambient_temp <= 30: temp_factor = 0.6
        elif ambient_temp <= 36: temp_factor = 0.85
        else:                    temp_factor = 1.0
        ac_kwh_per_km = (5.0 / max(avg_speed, 10)) * temp_factor

    traffic_mult = {
        'low':1.00,'normal':1.10,'high':1.25,'jam':1.45
    }.get(traffic_level, 1.10)

    passenger_kwh_per_km = base_kwh_per_km * 0.15
    kwh_per_km = (base_kwh_per_km + passenger_kwh_per_km + ac_kwh_per_km) * traffic_mult

    last = route_stops[-1]
    db   = get_db()
    cur  = db.cursor(dictionary=True)
    # ✅ CHANGED: latitude > 10
    cur.execute("SELECT * FROM charging_stations WHERE is_available=1 AND latitude > 10")
    stations = cur.fetchall()
    db.close()

    nearest, min_dist = None, float('inf')
    for s in stations:
        d = haversine(last['lat'], last['lon'], s['latitude'], s['longitude'])
        if d < min_dist:
            min_dist, nearest = d, s

    energy_station = min_dist * kwh_per_km if nearest else 0
    est_min        = round((min_dist / 30) * 60) if nearest else 0

    last_safe_idx  = 0
    last_safe_name = route_stops[0]['name']
    can_complete   = False
    cumulative     = 0

    for i, stop in enumerate(route_stops):
        seg        = stop['km'] if i == 0 else stop['km'] - route_stops[i-1]['km']
        cumulative += seg * kwh_per_km
        if battery_kwh >= (cumulative + energy_station):
            last_safe_idx  = i
            last_safe_name = stop['name']
            if i == len(route_stops) - 1:
                can_complete = True

    total_route  = route_stops[-1]['km'] * kwh_per_km
    total_needed = total_route + energy_station
    route_km     = route_stops[-1]['km']

    return {
        "battery_kwh"            : round(battery_kwh, 1),
        "kwh_per_km"             : round(kwh_per_km, 3),
        "total_route_energy_kwh" : round(total_route, 2),
        "energy_to_station_kwh"  : round(energy_station, 2),
        "total_needed_kwh"       : round(total_needed, 2),
        "can_complete_route"     : can_complete,
        "last_safe_stop_idx"     : last_safe_idx,
        "last_safe_stop_name"    : last_safe_name,
        "breakdown": {
            "base_kwh"      : round(base_kwh_per_km * route_km * traffic_mult, 2),
            "passenger_kwh" : round(passenger_kwh_per_km * route_km * traffic_mult, 2),
            "ac_kwh"        : round(ac_kwh_per_km * route_km * traffic_mult, 2),
            "traffic_kwh"   : round((base_kwh_per_km+passenger_kwh_per_km+ac_kwh_per_km)
                                    * (traffic_mult-1.0) * route_km, 2),
        },
        "conditions": {
            "passenger_assumption": "Worst case — full bus (50/50)",
            "ac_load_pct"         : round(temp_factor * 100),
            "traffic_penalty_pct" : round((traffic_mult - 1.0) * 100),
        },
        "nearest_station": {
            "name"        : nearest['name'],
            "distance_km" : round(min_dist, 2),
            "charger_type": nearest.get('charger_type', ''),
            "latitude"    : nearest['latitude'],
            "longitude"   : nearest['longitude'],
            "est_minutes" : est_min,
        } if nearest else None,
    }

@app.route('/')
def home():
    return render_template('dashboard.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    db   = get_db()
    cur  = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM drivers WHERE license_no=%s AND password=%s",
                (data['license_no'], data['password']))
    driver = cur.fetchone()
    db.close()
    if driver:
        return jsonify({"success":True,"driver_id":driver['id'],"name":driver['name']})
    return jsonify({"success":False,"message":"Invalid license number or password"}), 401

@app.route('/api/register', methods=['POST'])
def register():
    data       = request.json
    name       = data.get('name','').strip()
    license_no = data.get('license_no','').strip()
    password   = data.get('password','').strip()
    phone      = data.get('phone','').strip()
    if not name or not license_no or not password:
        return jsonify({"success":False,"message":"Name, license number and password are required"}), 400
    try:
        db  = get_db()
        cur = db.cursor()
        cur.execute("INSERT INTO drivers (name, license_no, phone, password) VALUES (%s, %s, %s, %s)",
                    (name, license_no, phone, password))
        db.commit()
        driver_id = cur.lastrowid
        db.close()
        return jsonify({"success":True,"driver_id":driver_id,"message":f"Driver '{name}' registered successfully!"})
    except Exception as e:
        return jsonify({"success":False,"message":"License number already exists. Please use a different one."}), 400

@app.route('/api/drivers', methods=['GET'])
def get_drivers():
    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, name, license_no, phone, created_at FROM drivers ORDER BY id DESC")
    drivers = cur.fetchall()
    db.close()
    for d in drivers:
        if d.get('created_at'):
            d['created_at'] = str(d['created_at'])
    return jsonify(drivers)

@app.route('/api/battery-analysis', methods=['POST'])
def battery_analysis():
    data = request.json
    # ✅ CHANGED: Tirupati → Tirumala stops
    stops = [
        {"name":"Tirupati CBS (Central Bus Station)", "lat":13.6288, "lon":79.4192, "km":0.0},
        {"name":"Alipiri",                            "lat":13.6388, "lon":79.4074, "km":3.5},
        {"name":"Kapila Theertham",                   "lat":13.6420, "lon":79.4010, "km":5.2},
        {"name":"Srinivasa Mangapuram",               "lat":13.6550, "lon":79.3900, "km":8.0},
        {"name":"Tirumala Ghat Road Mid",             "lat":13.6690, "lon":79.3710, "km":13.0},
        {"name":"Tirumala Bus Stand",                 "lat":13.6833, "lon":79.3478, "km":19.0},
    ]
    return jsonify(analyze_battery(
        float(data.get('battery_pct',80)), float(data.get('battery_capacity',200)),
        stops, float(data.get('avg_speed',35)), bool(int(data.get('ac_on',1))),
        float(data.get('ambient_temp',35)), data.get('traffic_level','normal')
    ))

@app.route('/api/trip/start', methods=['POST'])
def start_trip():
    data = request.json
    db   = get_db()
    cur  = db.cursor()
    cur.execute("INSERT INTO trips (bus_id,driver_id,route_id,battery_start_pct,status) VALUES (%s,%s,%s,%s,'active')",
                (data['bus_id'],data['driver_id'],data['route_id'],data['battery_start_pct']))
    db.commit()
    trip_id = cur.lastrowid
    db.close()
    active_trip["trip_id"]         = trip_id
    active_trip["current_stop_id"] = 1
    live_pax_count["count"]        = 0
    return jsonify({"success":True,"trip_id":trip_id})

@app.route('/api/active-trip', methods=['GET'])
def get_active_trip():
    if active_trip["trip_id"]:
        return jsonify({"trip_id":active_trip["trip_id"],"current_stop_id":active_trip["current_stop_id"]})
    return jsonify({"trip_id":None}), 404

@app.route('/api/update-stop', methods=['POST'])
def update_stop():
    active_trip["current_stop_id"] = request.json.get('stop_id', 1)
    return jsonify({"success":True})

@app.route('/api/set-passenger-count', methods=['POST'])
def set_passenger_count():
    data    = request.json
    trip_id = data.get('trip_id')
    stop_id = data.get('stop_id', 1)
    total   = max(0, min(int(data.get('total_onboard', 0)), 50))
    live_pax_count["count"] = total
    try:
        db  = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT total_onboard FROM passenger_events WHERE trip_id=%s ORDER BY id DESC LIMIT 1", (trip_id,))
        row   = cur.fetchone()
        prev  = row['total_onboard'] if row else 0
        delta = total - prev
        board  = max(0,  delta)
        alight = max(0, -delta)
        cur2 = db.cursor()
        cur2.execute("INSERT INTO passenger_events (trip_id,stop_id,boarded,alighted,total_onboard) VALUES (%s,%s,%s,%s,%s)",
                     (trip_id, stop_id, board, alight, total))
        db.commit()
        db.close()
    except Exception as e:
        print(f"DB error: {e}")
    return jsonify({"total_onboard":total,"load_percent":round(total/50*100,1),"seats_available":50-total})

@app.route('/api/current-pax', methods=['GET'])
def current_pax():
    count = live_pax_count["count"]
    return jsonify({"total_onboard":count,"load_percent":round(count/50*100,1),"seats_available":50-count})

@app.route('/api/passenger-event', methods=['POST'])
def passenger_event():
    data     = request.json
    trip_id  = data['trip_id']
    stop_id  = data['stop_id']
    boarded  = int(data['boarded'])
    alighted = int(data['alighted'])
    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT total_onboard FROM passenger_events WHERE trip_id=%s ORDER BY id DESC LIMIT 1", (trip_id,))
    row   = cur.fetchone()
    prev  = row['total_onboard'] if row else 0
    total = max(0, min(prev+boarded-alighted, 50))
    live_pax_count["count"] = total
    cur2 = db.cursor()
    cur2.execute("INSERT INTO passenger_events (trip_id,stop_id,boarded,alighted,total_onboard) VALUES (%s,%s,%s,%s,%s)",
                 (trip_id,stop_id,boarded,alighted,total))
    db.commit()
    db.close()
    return jsonify({"total_onboard":total,"load_percent":round(total/50*100,1),"seats_available":50-total})

@app.route('/api/predict', methods=['POST'])
def predict_energy():
    data = request.json
    try:
        traffic_encoded = encoder.transform([data['traffic_level']])[0]
    except:
        traffic_encoded = {'low':1,'normal':2,'high':0,'jam':3}.get(data['traffic_level'],2)

    features = pd.DataFrame([{
        'distance_km'    : float(data['distance_km']),
        'avg_speed_kmh'  : float(data['speed_kmh']),
        'passenger_count': int(data['passenger_count']),
        'ac_on'          : int(data['ac_on']),
        'ambient_temp_c' : float(data['ambient_temp_c']),
        'traffic_encoded': traffic_encoded
    }])
    predicted_kwh = round(float(model.predict(features)[0]), 2)

    battery_pct           = float(data['battery_pct'])
    battery_capacity      = float(data.get('battery_capacity_kwh', 200))
    battery_remaining_kwh = battery_capacity * battery_pct / 100
    km_remaining          = float(data.get('km_remaining', 10))
    kwh_per_km            = predicted_kwh / max(float(data['distance_km']), 0.1)
    range_km              = round(battery_remaining_kwh / kwh_per_km, 1)
    can_complete          = battery_remaining_kwh >= (km_remaining * kwh_per_km)

    # ✅ CHANGED: Tirupati default coordinates
    lat = float(data.get('latitude',  13.6550))
    lon = float(data.get('longitude', 79.3900))
    smart_stations = get_smart_stations(lat, lon, kwh_per_km, battery_remaining_kwh, km_remaining)
    nearest = smart_stations[0] if smart_stations else None

    alert, alert_level = None, None
    if battery_pct <= 10:
        if nearest and nearest['can_reach_station']:
            alert = (f"CRITICAL — Battery very low ({battery_pct:.1f}%)! "
                     f"Go to {nearest['name']} ({nearest['distance_km']} km, "
                     f"~{nearest['est_minutes']} mins). Needs {nearest['energy_to_reach_kwh']} kWh.")
        else:
            alert = f"CRITICAL — Battery at {battery_pct:.1f}%! No station reachable. Stop bus immediately!"
        alert_level = "critical"
    elif battery_pct <= 20:
        if nearest and nearest['can_finish_then_charge']:
            alert = (f"LOW BATTERY — {battery_pct:.1f}%. Complete route then "
                     f"charge at {nearest['name']} ({nearest['distance_km']} km, ~{nearest['est_minutes']} mins).")
            alert_level = "low"
        elif nearest and nearest['can_reach_station']:
            alert = (f"LOW BATTERY — Head to {nearest['name']} now "
                     f"({nearest['distance_km']} km, ~{nearest['est_minutes']} mins, "
                     f"needs {nearest['energy_to_reach_kwh']} kWh).")
            alert_level = "low"
        else:
            alert = "CRITICAL — Battery low and no station reachable! Stop bus!"
            alert_level = "critical"
    elif not can_complete:
        if nearest and nearest['can_reach_station']:
            alert = (f"WARNING — Cannot complete route. "
                     f"Nearest charger: {nearest['name']} ({nearest['distance_km']} km, ~{nearest['est_minutes']} mins).")
            alert_level = "warning"
        else:
            alert = "WARNING — Cannot complete route and no station reachable!"
            alert_level = "critical"

    if data.get('trip_id'):
        try:
            db  = get_db()
            cur = db.cursor()
            cur.execute("""INSERT INTO trip_segments
                (trip_id,km_travelled,speed_kmh,passenger_count,ac_on,
                 ambient_temp_c,traffic_level,energy_consumed_kwh,battery_pct)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (data['trip_id'],data['distance_km'],data['speed_kmh'],
                 data['passenger_count'],data['ac_on'],data['ambient_temp_c'],
                 data['traffic_level'],predicted_kwh,battery_pct))
            if alert and nearest:
                cur.execute("""INSERT INTO battery_alerts
                    (trip_id,battery_pct,km_remaining,alert_type,nearest_station)
                    VALUES (%s,%s,%s,%s,%s)""",
                    (data['trip_id'],battery_pct,km_remaining,alert_level,nearest['name']))
            db.commit()
            db.close()
        except Exception as e:
            print(f"DB error: {e}")

    return jsonify({
        "predicted_kwh"         : predicted_kwh,
        "battery_remaining_kwh" : round(battery_remaining_kwh, 2),
        "estimated_range_km"    : range_km,
        "can_complete_route"    : can_complete,
        "kwh_per_km"            : round(kwh_per_km, 3),
        "alert"                 : alert,
        "alert_level"           : alert_level,
        "smart_stations"        : smart_stations,
    })

@app.route('/api/trip/end', methods=['POST'])
def end_trip():
    data = request.json
    db   = get_db()
    cur  = db.cursor()
    cur.execute("""UPDATE trips SET status='completed',end_time=NOW(),
                   battery_end_pct=%s,total_km_covered=%s,total_energy_kwh=%s
                   WHERE id=%s""",
                (data['battery_end_pct'],data['total_km'],data['total_energy_kwh'],data['trip_id']))
    db.commit()
    db.close()
    active_trip["trip_id"]  = None
    live_pax_count["count"] = 0
    return jsonify({"success":True,"message":"Trip completed"})

if __name__ == '__main__':
    print("Starting APSRTC Smart Bus API server...")
    print("Dashboard: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)