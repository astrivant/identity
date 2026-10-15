SELECT
    current_setting('synchronous_commit') AS commit_policy,
    current_setting('fsync') AS fsync_policy;
