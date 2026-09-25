-- Charging network operations. ALL DATA IS SYNTHETIC.
--
-- Three tables, because one table only supports one kind of question.
-- Operations teams ask about uptime, utilisation and revenue — all of
-- which need sessions and faults, not just an asset list.

DROP TABLE IF EXISTS faults, sessions, stations CASCADE;

CREATE TABLE stations (
    id              SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,      -- e.g. PNQ-007
    name            TEXT        NOT NULL,
    operator        TEXT        NOT NULL,
    city            TEXT        NOT NULL,
    state           TEXT        NOT NULL,
    connectors      INTEGER     NOT NULL,
    power_kw        NUMERIC(6,1) NOT NULL,
    connector_type  TEXT        NOT NULL,      -- CCS2 | Type2 | CHAdeMO
    status          TEXT        NOT NULL,      -- live | maintenance | planned
    commissioned_on DATE
);

CREATE TABLE sessions (
    id             SERIAL PRIMARY KEY,
    station_id     INTEGER NOT NULL REFERENCES stations(id),
    connector_no   INTEGER NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL,
    ended_at       TIMESTAMPTZ,
    energy_kwh     NUMERIC(8,2),
    amount_inr     NUMERIC(10,2),
    payment_status TEXT NOT NULL,              -- paid | failed | pending
    -- Personal data. Day 11 masks all four of these at the boundary so they
    -- never reach a model. They are here because real session tables have them.
    driver_name    TEXT,
    driver_phone   TEXT,
    driver_email   TEXT,
    vehicle_reg    TEXT
);

CREATE TABLE faults (
    id           SERIAL PRIMARY KEY,
    station_id   INTEGER NOT NULL REFERENCES stations(id),
    connector_no INTEGER,
    code         TEXT NOT NULL,                -- e.g. GROUND_FAULT
    description  TEXT NOT NULL,
    severity     TEXT NOT NULL,                -- critical | major | minor
    raised_at    TIMESTAMPTZ NOT NULL,
    resolved_at  TIMESTAMPTZ                   -- NULL = still open
);

CREATE INDEX sessions_station_idx ON sessions (station_id, started_at);
CREATE INDEX faults_station_idx   ON faults   (station_id, raised_at);
CREATE INDEX stations_city_idx    ON stations (city);
