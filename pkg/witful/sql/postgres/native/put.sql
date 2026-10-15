INSERT INTO witful_native_objects (tenant, identity_id, id, payload) VALUES (%s, %s, %s, %s)
ON CONFLICT (tenant, identity_id, id) DO NOTHING;
