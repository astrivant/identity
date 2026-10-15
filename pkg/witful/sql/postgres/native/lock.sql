INSERT INTO witful_native_heads (tenant, identity_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;
