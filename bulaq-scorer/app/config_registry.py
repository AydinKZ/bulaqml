import json
import logging
import psycopg
from psycopg.rows import dict_row


class ConfigRegistryRepo:
    def __init__(self, settings):
        self.settings = settings
        self.conn = None

    def init(self):
        if not self.settings.pg_dsn:
            return

        try:
            self.conn = psycopg.connect(self.settings.pg_dsn, autocommit=True, row_factory=dict_row)
            with self.conn.cursor() as cur:
                cur.execute("""
                    create table if not exists scorer_config (
                        id bigserial primary key,
                        config_name text not null unique,
                        description text null,
                        config_json jsonb not null,
                        created_at timestamptz not null default now(),
                        created_by text null,
                        source text not null default 'ui',
                        is_active boolean not null default false,
                        activated_at timestamptz null,
                        cfg_runtime_id bigint null
                    )
                """)
                cur.execute("""
                    create table if not exists scorer_config_history (
                        id bigserial primary key,
                        event_type text not null,
                        config_id bigint null references scorer_config(id) on delete set null,
                        config_name text null,
                        cfg_runtime_id bigint null,
                        reset_mode text null,
                        scope text null default 'global',
                        details_json jsonb null,
                        created_at timestamptz not null default now(),
                        created_by text null,
                        source text not null default 'ui'
                    )
                """)
        except Exception as e:
            self.conn = None
            logging.getLogger("bulaq-scorer").warning("Postgres config registry disabled: %r", e)

    def save_config(self, config_name, description, config, created_by, source, cfg_runtime_id):
        if self.conn is None:
            raise RuntimeError("Postgres not configured")

        with self.conn.cursor() as cur:
            cur.execute(
                """
                insert into scorer_config
                    (config_name, description, config_json, created_by, source, is_active, cfg_runtime_id)
                values
                    (%s, %s, %s::jsonb, %s, %s, false, %s)
                returning id
                """,
                (config_name, description, json.dumps(config), created_by, source, cfg_runtime_id),
            )
            row = cur.fetchone()
            config_id = row["id"]

            cur.execute(
                """
                insert into scorer_config_history
                    (event_type, config_id, config_name, cfg_runtime_id, details_json, created_by, source)
                values
                    (%s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                ("save", config_id, config_name, cfg_runtime_id, json.dumps({"description": description}), created_by, source),
            )

        return config_id

    def list_configs(self, limit=100):
        if self.conn is None:
            return []

        with self.conn.cursor() as cur:
            cur.execute(
                """
                select id, config_name, description, created_at, created_by, source,
                       is_active, activated_at, cfg_runtime_id
                from scorer_config
                order by created_at desc
                limit %s
                """,
                (limit,),
            )
            return cur.fetchall()

    def get_config(self, config_id: int):
        if self.conn is None:
            raise RuntimeError("Postgres not configured")

        with self.conn.cursor() as cur:
            cur.execute("select * from scorer_config where id = %s", (config_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(f"config_id {config_id} not found")
            return row

    def activate_config(self, config_id, cfg_runtime_id, reset_mode, scope, activated_by, source):
        if self.conn is None:
            raise RuntimeError("Postgres not configured")

        with self.conn.cursor() as cur:
            cur.execute("update scorer_config set is_active = false where is_active = true")
            cur.execute(
                """
                update scorer_config
                set is_active = true,
                    activated_at = now(),
                    cfg_runtime_id = %s
                where id = %s
                returning config_name
                """,
                (cfg_runtime_id, config_id),
            )
            row = cur.fetchone()
            config_name = row["config_name"] if row else None

            cur.execute(
                """
                insert into scorer_config_history
                    (event_type, config_id, config_name, cfg_runtime_id, reset_mode, scope, created_by, source)
                values
                    (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                ("apply", config_id, config_name, cfg_runtime_id, reset_mode, scope, activated_by, source),
            )

        return config_name

    def close(self):
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass