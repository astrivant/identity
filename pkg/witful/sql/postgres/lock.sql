-- Fixed application lock serializes schema bootstrap and concurrent journal ingestion.
SELECT pg_advisory_xact_lock(1936746866, 1);
