from flask import Flask, render_template, jsonify
import requests
import json
import pandas as pd
from datetime import datetime


def unix_to_hhmm(ts):
    return datetime.fromtimestamp(ts).strftime('%H:%M')


app = Flask(__name__)

# load gtfs
routes_df = pd.read_csv('./routes.txt')
trips_df = pd.read_csv('./trips.txt')
stops_df = pd.read_csv('./stops.txt')

with open('buses.json') as f:
    bus_types = json.load(f)

API_KEY = 'PLACEHOLDER API KEY'
HEADERS = {"Ocp-Apim-Subscription-Key": API_KEY}

route_color_map = routes_df.set_index("route_id")["route_color"].fillna("000000").to_dict()
trips_df["trip_id"] = trips_df["trip_id"].astype(str)
trip_headsign_map = trips_df.set_index("trip_id")["trip_headsign"].to_dict()

stop_name_map = stops_df.set_index('stop_id')['stop_name'].to_dict()

trip_fallback_map = trips_df.set_index(["route_id", "direction_id"])["trip_headsign"].to_dict()


# routes

@app.route('/')
def index():
    return render_template('map.html')


@app.route('/api/vehicles')
def vehicles():
    vp_url = 'https://nextrip-public-api.azure-api.net/octranspo/gtfs-rt-vp/beta/v1/VehiclePositions?format=JSON'
    response = requests.get(vp_url, headers=HEADERS)
    data = response.json()

    tu_url = 'https://nextrip-public-api.azure-api.net/octranspo/gtfs-rt-tp/beta/v1/TripUpdates?format=JSON'
    tu_response = requests.get(tu_url, headers=HEADERS)
    tu_data = tu_response.json()

    buses = []

    trip_updates = {}
    for entity in tu_data.get("Entity", []):
        tu = entity.get("TripUpdate")
        if not isinstance(tu, dict):
            continue

        trip = tu.get("Trip")
        if not isinstance(trip, dict):
            continue

        trip_id = str(trip.get("TripId"))
        stop_time_updates = tu.get("StopTimeUpdate", [])

        if trip_id and stop_time_updates:
            trip_updates[trip_id] = stop_time_updates

    for entity in data.get("Entity", []):
        vehicle = entity.get("Vehicle", {})
        trip = vehicle.get("Trip", {})
        position = vehicle.get("Position", {})
        vehicle_info = vehicle.get("Vehicle", {})
        vehicle_id = vehicle_info.get("Id")

        if not position or not trip or not vehicle_id:
            continue

        route_id = trip.get("RouteId")
        trip_id = trip.get("TripId")
        direction_id = trip.get("DirectionId", 0)

        # get color
        route_color = f"#{route_color_map.get(route_id, '000000')}"
        if "ffffff" in route_color.lower():
            route_color = "#aeb3bd"

        # get direction
        direction_name = trip_headsign_map.get(str(trip_id))
        if not direction_name:
            direction_name = trip_fallback_map.get((route_id, direction_id), "Unknown")

        # get bud type
        try:
            vehicle_num = int(vehicle_id)
        except ValueError:
            vehicle_num = -1

        bus_type = "Unknown"
        for b in bus_types:
            if b["min"] <= vehicle_num <= b["max"]:
                bus_type = b["name"]
                break

        next_stop = None
        scheduled_time = None
        actual_time = None
        delay_minutes = None

        updates = trip_updates.get(str(trip_id))
        if updates:
            for stop_update in updates:
                arrival = stop_update.get("Arrival", {})
                if not arrival:
                    continue
                time_unix = arrival.get("Time")
                if time_unix:
                    scheduled = arrival.get("ScheduledArrivalTime", time_unix)
                    stop_id = str(stop_update.get("StopId"))
                    raw_name = stop_name_map.get(stop_id, stop_id)
                    next_stop = raw_name.title() if isinstance(raw_name, str) else raw_name
                    scheduled_time = unix_to_hhmm(scheduled)
                    actual_time = unix_to_hhmm(time_unix)
                    delay_minutes = round((time_unix - scheduled) / 60)
                    break

        buses.append({
            "lat": position["Latitude"],
            "lon": position["Longitude"],
            "bearing": position.get("Bearing", 0),
            "route_id": route_id,
            "trip_id": trip_id,
            "speed": round(position.get("Speed", 0), 1),
            "vehicle_id": vehicle_id,
            "direction": direction_name,
            "route_color": route_color,
            "bus_type": bus_type,
            "next_stop": next_stop,
            "scheduled_time": scheduled_time,
            "actual_time": actual_time,
            "delay_minutes": delay_minutes
        })

    return jsonify(buses)


@app.route('/api/bus_types')
def get_bus_types():
    return jsonify(bus_types)


if __name__ == '__main__':
    app.run(debug=True, port=8888)
