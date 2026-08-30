DO $$
DECLARE
    uid INT;
    t_name text;
BEGIN
    FOR uid IN SELECT id FROM users WHERE username = 'testuser' LOOP
        FOR t_name IN SELECT table_name FROM information_schema.columns WHERE column_name='user_id' AND table_schema='public' LOOP
            EXECUTE format('DELETE FROM %I WHERE user_id = %L', t_name, uid);
        END LOOP;
        DELETE FROM users WHERE id = uid;
    END LOOP;
END $$;
