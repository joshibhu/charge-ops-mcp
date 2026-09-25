-- The login the MCP SERVER uses. It cannot write.
--
-- Everything above this (the tool list, the dispatcher, the SQL guard on
-- Day 10) is code I wrote, and my code has bugs. This layer is Postgres
-- refusing, which is why it is the one that holds.

DROP ROLE IF EXISTS ops_reader;
CREATE ROLE ops_reader LOGIN PASSWORD 'reader_dev_password';

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ops_reader;
REVOKE ALL ON SCHEMA public FROM ops_reader;

GRANT CONNECT ON DATABASE chargeops TO ops_reader;
GRANT USAGE   ON SCHEMA public      TO ops_reader;
GRANT SELECT  ON ALL TABLES IN SCHEMA public TO ops_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ops_reader;

-- Second, independent mechanism: even a mistakenly granted write is refused.
ALTER ROLE ops_reader SET default_transaction_read_only = on;

-- A runaway query cannot pin the database. 9,000 sessions makes this real.
ALTER ROLE ops_reader SET statement_timeout = '8s';
