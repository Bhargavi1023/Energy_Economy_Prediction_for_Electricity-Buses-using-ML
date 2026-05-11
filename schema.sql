-- ============================================================
-- Smart Electric Bus Energy Management System
-- MySQL Database Schema — TIRUPATI VERSION (Fixed)
-- HOW TO USE: Open MySQL Workbench → New Query → Paste this → Run (Ctrl+Shift+Enter)
-- ============================================================

-- FIX 1: Drop and recreate fresh (avoids duplicate data errors)
DROP DATABASE IF EXISTS smart_bus_db;
CREATE DATABASE smart_bus_db;
USE smart_bus_db;

-- =============================================
-- TABLES
-- =============================================

CREATE TABLE drivers (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    license_no VARCHAR(50)  UNIQUE NOT NULL,
    phone      VARCHAR(20),
    password   VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE buses (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    bus_number                  VARCHAR(20) UNIQUE NOT NULL,
    max_passengers              INT   DEFAULT 50,
    battery_capacity_kwh        FLOAT DEFAULT 200.0,
    base_consumption_kwh_per_km FLOAT DEFAULT 1.2,
    ac_overhead_kw              FLOAT DEFAULT 5.0
);

CREATE TABLE routes (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    route_name VARCHAR(100) NOT NULL,
    total_km   FLOAT NOT NULL
);

CREATE TABLE stops (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    route_id     INT,
    stop_name    VARCHAR(100) NOT NULL,
    stop_order   INT   NOT NULL,
    km_from_start FLOAT DEFAULT 0,
    FOREIGN KEY (route_id) REFERENCES routes(id)
);

CREATE TABLE trips (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    bus_id            INT,
    driver_id         INT,
    route_id          INT,
    start_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time          TIMESTAMP NULL,
    battery_start_pct FLOAT NOT NULL,
    battery_end_pct   FLOAT,
    total_km_covered  FLOAT DEFAULT 0,
    total_energy_kwh  FLOAT DEFAULT 0,
    status            VARCHAR(20) DEFAULT 'active',
    FOREIGN KEY (bus_id)    REFERENCES buses(id),
    FOREIGN KEY (driver_id) REFERENCES drivers(id),
    FOREIGN KEY (route_id)  REFERENCES routes(id)
);

CREATE TABLE trip_segments (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    trip_id             INT,
    segment_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    km_travelled        FLOAT   DEFAULT 0,
    speed_kmh           FLOAT   DEFAULT 0,
    passenger_count     INT     DEFAULT 0,
    ac_on               BOOLEAN DEFAULT FALSE,
    ambient_temp_c      FLOAT,
    traffic_level       VARCHAR(20) DEFAULT 'normal',
    energy_consumed_kwh FLOAT DEFAULT 0,
    battery_pct         FLOAT,
    FOREIGN KEY (trip_id) REFERENCES trips(id)
);

CREATE TABLE passenger_events (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    trip_id      INT,
    stop_id      INT,
    event_time   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    boarded      INT DEFAULT 0,
    alighted     INT DEFAULT 0,
    total_onboard INT DEFAULT 0,
    FOREIGN KEY (trip_id) REFERENCES trips(id),
    -- FIX 2: stop_id FK removed (stops table uses route stops, not sid from frontend)
    -- This was causing FK constraint errors when inserting passenger events
    INDEX idx_trip_id (trip_id)
);

CREATE TABLE charging_stations (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    latitude     FLOAT NOT NULL,
    longitude    FLOAT NOT NULL,
    charger_type VARCHAR(50),
    power_kw     FLOAT,
    is_available BOOLEAN DEFAULT TRUE
);

CREATE TABLE battery_alerts (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    trip_id         INT,
    alert_time      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    battery_pct     FLOAT,
    km_remaining    FLOAT,
    alert_type      VARCHAR(30),
    nearest_station VARCHAR(100),
    FOREIGN KEY (trip_id) REFERENCES trips(id)
);

-- =============================================
-- SAMPLE DATA
-- =============================================

-- Drivers (AP license format for Tirupati)
INSERT INTO drivers (name, license_no, phone, password) VALUES
('Raju Kumar',   'AP03-2021-0001234', '9866123456', 'driver123'),
('Suresh Babu',  'AP03-2020-0005678', '9848765432', 'driver456'),
('Venkat Rao',   'AP03-2019-0009999', '9912345678', 'driver789');

-- Buses
INSERT INTO buses (bus_number, max_passengers, battery_capacity_kwh, base_consumption_kwh_per_km, ac_overhead_kw) VALUES
('APSRTC-EV-001', 50, 200.0, 1.2, 5.0),
('APSRTC-EV-002', 50, 200.0, 1.2, 5.0),
('APSRTC-EV-003', 40, 160.0, 1.0, 4.5);

-- Route: Tirupati → Tirumala (19 km)
INSERT INTO routes (route_name, total_km) VALUES
('Tirupati CBS to Tirumala', 19.0),
('Airport Express',          35.0),
('City Local Route',         12.0);

-- Stops: Tirupati → Tirumala real stops
INSERT INTO stops (route_id, stop_name, stop_order, km_from_start) VALUES
(1, 'Tirupati CBS (Central Bus Station)', 1,  0.0),
(1, 'Alipiri',                            2,  3.5),
(1, 'Kapila Theertham',                   3,  5.2),
(1, 'Srinivasa Mangapuram',               4,  8.0),
(1, 'Tirumala Ghat Road Mid',             5, 13.0),
(1, 'Tirumala Bus Stand',                 6, 19.0);

-- FIX 3: Charging stations updated to Tirupati area
-- OLD stations were in Vijayawada (453 km away!) → caused 686 kWh error
-- NEW stations are correct Tirupati locations
INSERT INTO charging_stations (name, latitude, longitude, charger_type, power_kw, is_available) VALUES
('Tirumala Bus Stand Charger',   13.6833, 79.3478, 'DC Fast 60kW',  60.0,  TRUE),
('Alipiri EV Charging Depot',    13.6388, 79.4074, 'DC Fast 150kW', 150.0, TRUE),
('Tirupati CBS Depot Charger',   13.6288, 79.4192, 'AC 22kW',        22.0, TRUE),
('Renigunta Airport Depot',      13.6470, 79.5180, 'DC Fast 100kW', 100.0, TRUE);

-- =============================================
-- VERIFY (run after import to confirm)
-- =============================================
-- SELECT * FROM drivers;
-- SELECT * FROM charging_stations;
-- SELECT * FROM stops WHERE route_id = 1;