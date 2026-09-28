-- The schema the MODEL is allowed to see.
--
-- Python masking keys on the output COLUMN NAME, and with run_sql the model
-- chooses the names: `SELECT driver_name AS city` defeated it completely, as
-- did upper(), || and substring(). Any name-based filter fails when the other
-- side picks the names.
--
-- So the raw values are made UNREACHABLE instead of filtered. ops_reader
-- loses access to the sessions table entirely and gets this view instead,
-- where the masking is already applied. Renaming a masked value just renames
-- a masked value.

DROP VIEW IF EXISTS sessions_safe;

CREATE VIEW sessions_safe AS
SELECT
    id, station_id, connector_no,
    started_at, ended_at,
    energy_kwh, amount_inr, payment_status,

    -- 'Divya Kulkarni' -> 'D*** K***'   (first letter of each word survives)
    regexp_replace(driver_name, '(\S)\S*', '\1***', 'g')            AS driver_name,

    -- '+919572623548' -> '+91*****3548'  (last 4 match a support ticket)
    CASE WHEN driver_phone IS NULL THEN NULL ELSE
        '+91'
        || repeat('*', greatest(1, length(regexp_replace(driver_phone,'\D','','g')) - 7))
        || right(regexp_replace(driver_phone,'\D','','g'), 4)
    END                                                              AS driver_phone,

    -- 'divya.k15@example.com' -> 'd***@example.com'  (domain kept on purpose)
    CASE WHEN driver_email IS NULL THEN NULL ELSE
        left(split_part(driver_email,'@',1), 1) || '***@'
        || split_part(driver_email,'@',2)
    END                                                              AS driver_email,

    -- 'GJ01CC1814' -> 'GJ01****1814'  (state + district code survive)
    CASE WHEN vehicle_reg IS NULL THEN NULL ELSE
        left(vehicle_reg, 4) || '****' || right(vehicle_reg, 4)
    END                                                              AS vehicle_reg
FROM sessions;

-- The grant is what makes the view real. A view hides nothing from a role
-- that can still read the underlying table.
REVOKE ALL ON sessions FROM ops_reader;
GRANT SELECT ON sessions_safe TO ops_reader;
