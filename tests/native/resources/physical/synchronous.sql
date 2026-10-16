SELECT count(*) FROM pg_stat_replication
WHERE application_name = 'native_drill' AND sync_state = 'sync';
