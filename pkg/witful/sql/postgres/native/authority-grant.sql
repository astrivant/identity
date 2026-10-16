SELECT
    subject,
    task_id,
    actions,
    records,
    starts_at,
    expires
FROM witful_native_admit_grant(%s, %s, %s, %s);
