"""Generate synthetic operations data.

Everything here is invented — operators, drivers, phone numbers, sites.
Cities are real; nothing else is. Safe to publish.

Deliberate imperfections, because clean data teaches nothing:
  - some sessions never ended (driver unplugged, meter lost)
  - some payments failed
  - a few faults are still open
  - one station is a genuine problem site, so "which site is worst" has
    a real answer rather than noise

    uv run python db/seed.py
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent

random.seed(42)  # reproducible: the same data every run

DSN = os.environ.get(
    "SEED_DSN", "postgresql://ops_owner:dev_only_not_a_secret@localhost:5434/chargeops"
)

OPERATORS = ["VoltGrid", "ChargeNova", "PowerLoop", "Ampere Networks"]
CITIES = [
    ("Pune", "Maharashtra", "PNQ"),
    ("Bengaluru", "Karnataka", "BLR"),
    ("Mumbai", "Maharashtra", "BOM"),
    ("New Delhi", "Delhi", "DEL"),
    ("Chennai", "Tamil Nadu", "MAA"),
    ("Hyderabad", "Telangana", "HYD"),
    ("Gurugram", "Haryana", "GGN"),
    ("Ahmedabad", "Gujarat", "AMD"),
]
SITE_WORDS = [
    "Tech Park", "Mall Hub", "Metro Station", "Highway Plaza", "Business Bay",
    "Airport Link", "Industrial Estate", "Riverside", "Central Square",
    "Ring Road", "Expressway Stop", "City Centre",
]
CONNECTORS = [("CCS2", [60, 120, 150]), ("Type2", [11, 22]), ("CHAdeMO", [50])]

FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vikram",
         "Priya", "Arjun", "Sneha", "Rahul", "Nisha", "Karan", "Divya"]
LAST = ["Sharma", "Patel", "Reddy", "Iyer", "Nair", "Gupta", "Mehta",
        "Singh", "Rao", "Joshi", "Desai", "Kulkarni"]

FAULT_TYPES = [
    ("GROUND_FAULT", "Residual current detected on the AC side", "critical"),
    ("OVER_TEMP", "Power module temperature above threshold", "major"),
    ("COMMS_LOST", "Station lost backend connectivity", "major"),
    ("CONNECTOR_LOCK", "Connector lock actuator did not engage", "minor"),
    ("PAYMENT_TERMINAL", "Card reader unresponsive", "minor"),
    ("EMERGENCY_STOP", "Emergency stop pressed on site", "critical"),
]

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
DAYS = 90


def make_stations() -> list[tuple]:
    rows, seen = [], set()
    for city, state, prefix in CITIES:
        for n in range(1, random.randint(4, 7)):
            name = f"{city} {random.choice(SITE_WORDS)}"
            if name in seen:
                continue
            seen.add(name)
            ctype, powers = random.choice(CONNECTORS)
            rows.append((
                f"{prefix}-{n:03d}",
                name,
                random.choice(OPERATORS),
                city,
                state,
                random.choice([2, 2, 4, 4, 6, 8]),
                float(random.choice(powers)),
                ctype,
                random.choices(["live", "maintenance", "planned"], [88, 8, 4])[0],
                (NOW - timedelta(days=random.randint(120, 900))).date(),
            ))
    return rows


def make_sessions(station_ids: list[tuple[int, int, float, str]]) -> list[tuple]:
    """One row per charging session over the last DAYS days."""
    rows = []
    # One site is a genuine problem: high failure rate, low utilisation.
    problem_site = station_ids[3][0]

    for station_id, connectors, power_kw, status in station_ids:
        if status != "live":
            continue
        # Busier sites get more sessions; the problem site gets far fewer.
        per_day = random.uniform(1.5, 6.0) * (connectors / 4)
        if station_id == problem_site:
            per_day *= 0.35

        for day in range(DAYS):
            for _ in range(int(random.gauss(per_day, per_day * 0.4))):
                start = NOW - timedelta(
                    days=day, hours=random.randint(0, 23), minutes=random.randint(0, 59)
                )
                minutes = max(8, int(random.gauss(45, 20)))
                # ~2% of sessions never report an end — a real data problem.
                unfinished = random.random() < 0.02
                energy = round(power_kw * (minutes / 60) * random.uniform(0.45, 0.85), 2)
                tariff = round(random.uniform(13.0, 25.0), 2)

                failed_rate = 0.18 if station_id == problem_site else 0.04
                payment = random.choices(
                    ["paid", "failed", "pending"],
                    [1 - failed_rate - 0.01, failed_rate, 0.01],
                )[0]

                first, last = random.choice(FIRST), random.choice(LAST)
                rows.append((
                    station_id,
                    random.randint(1, connectors),
                    start,
                    None if unfinished else start + timedelta(minutes=minutes),
                    None if unfinished else energy,
                    None if unfinished else round(energy * tariff, 2),
                    payment,
                    f"{first} {last}",
                    f"+91{random.randint(70, 99)}{random.randint(10000000, 99999999)}",
                    f"{first.lower()}.{last.lower()}{random.randint(1, 99)}@example.com",
                    f"{random.choice(['MH12','KA01','DL3C','TN09','TS07','GJ01'])}"
                    f"{random.choice('ABCDEFGHJK')}{random.choice('ABCDEFGHJK')}"
                    f"{random.randint(1000, 9999)}",
                ))
    return rows


def make_faults(station_ids: list[tuple[int, int, float, str]]) -> list[tuple]:
    rows = []
    problem_site = station_ids[3][0]
    for station_id, connectors, _power, status in station_ids:
        count = random.randint(0, 4)
        if station_id == problem_site:
            count = random.randint(9, 14)
        if status == "maintenance":
            count += 3
        for _ in range(count):
            code, desc, sev = random.choice(FAULT_TYPES)
            raised = NOW - timedelta(
                days=random.randint(0, DAYS), hours=random.randint(0, 23)
            )
            # ~12% still open.
            open_now = random.random() < 0.12
            hours_down = random.choice([1, 2, 4, 8, 20, 48, 96])
            rows.append((
                station_id,
                random.randint(1, connectors) if random.random() < 0.8 else None,
                code, desc, sev, raised,
                None if open_now else raised + timedelta(hours=hours_down),
            ))
    return rows


def main() -> None:
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute((HERE / "01_schema.sql").read_text())

        stations = make_stations()
        cur.executemany(
            """INSERT INTO stations
               (code,name,operator,city,state,connectors,power_kw,
                connector_type,status,commissioned_on)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            stations,
        )

        cur.execute("SELECT id, connectors, power_kw, status FROM stations ORDER BY id")
        ids = [(r[0], r[1], float(r[2]), r[3]) for r in cur.fetchall()]

        sess = make_sessions(ids)
        cur.executemany(
            """INSERT INTO sessions
               (station_id,connector_no,started_at,ended_at,energy_kwh,amount_inr,
                payment_status,driver_name,driver_phone,driver_email,vehicle_reg)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            sess,
        )

        faults = make_faults(ids)
        cur.executemany(
            """INSERT INTO faults
               (station_id,connector_no,code,description,severity,raised_at,resolved_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            faults,
        )

        print(f"stations {len(stations)}   sessions {len(sess)}   faults {len(faults)}")


if __name__ == "__main__":
    main()
