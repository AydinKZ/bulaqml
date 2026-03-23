import json
import logging
from datetime import datetime, UTC

import psycopg
from psycopg.rows import dict_row


def _ts_us_to_dt(ts_us: int | None):
    if ts_us is None:
        return None
    return datetime.fromtimestamp(int(ts_us) / 1_000_000, UTC)


class LearnedTagsRepo:
    def __init__(self, settings):
        self.settings = settings
        self.conn = None

    def init(self):
        if not self.settings.pg_dsn:
            return

        try:
            self.conn = psycopg.connect(
                self.settings.pg_dsn,
                autocommit=True,
                row_factory=dict_row,
            )
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    create table if not exists learned_tags (
                        uuid text primary key,
                        vtype text not null check (vtype in ('numeric', 'bool', 'cat')),
                        collector_id text null,
                        discovery_date timestamptz not null default now(),
                        first_seen_ts timestamptz null,
                        last_seen_ts timestamptz null,

                        assigned_model text null,
                        model_settings_json jsonb not null default '{}'::jsonb,
                        enabled_for_scoring boolean not null default false,

                        status text not null default 'discovered'
                            check (status in ('discovered', 'assigned', 'active', 'disabled')),

                        notes text null,
                        last_value_text text null,
                        last_error text null,

                        created_at timestamptz not null default now(),
                        updated_at timestamptz not null default now()
                    )
                    """
                )

                cur.execute(
                    """
                    create index if not exists idx_learned_tags_status
                    on learned_tags(status)
                    """
                )
                cur.execute(
                    """
                    create index if not exists idx_learned_tags_vtype
                    on learned_tags(vtype)
                    """
                )
                cur.execute(
                    """
                    create index if not exists idx_learned_tags_last_seen_ts
                    on learned_tags(last_seen_ts desc)
                    """
                )

                cur.execute(
                    """
                    create table if not exists learned_tag_actions (
                        id bigserial primary key,
                        uuid text not null references learned_tags(uuid) on delete cascade,
                        action text not null,
                        payload_json jsonb not null default '{}'::jsonb,
                        actor text null,
                        source text null,
                        created_at timestamptz not null default now()
                    )
                    """
                )

                cur.execute(
                    """
                    create table if not exists learned_tag_model_history (
                        id bigserial primary key,
                        uuid text not null references learned_tags(uuid) on delete cascade,
                        assigned_at timestamptz not null default now(),
                        vtype text not null check (vtype in ('numeric', 'bool', 'cat')),
                        assigned_model text not null,
                        model_settings_json jsonb not null default '{}'::jsonb,
                        actor text null,
                        source text not null default 'ui'
                    )
                    """
                )

                cur.execute(
                    """
                    create index if not exists idx_ltmh_uuid_assigned_at
                    on learned_tag_model_history(uuid, assigned_at desc)
                    """
                )

                cur.execute(
                    """
                    create index if not exists idx_ltmh_assigned_model
                    on learned_tag_model_history(assigned_model)
                    """
                )

                cur.execute(
                    """
                    create index if not exists idx_ltmh_assigned_at
                    on learned_tag_model_history(assigned_at desc)
                    """
                )

        except Exception as e:
            self.conn = None
            logging.getLogger("bulaq-scorer").warning("Postgres learned_tags disabled: %r", e)

    def close(self):
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass

    def count_tags(self) -> int:
        if self.conn is None:
            return 0
        with self.conn.cursor() as cur:
            cur.execute("select count(*) as n from learned_tags")
            row = cur.fetchone()
            return int(row["n"])

    def get_tag(self, uuid: str):
        if self.conn is None:
            return None
        with self.conn.cursor() as cur:
            cur.execute("select * from learned_tags where uuid = %s", (uuid,))
            return cur.fetchone()

    def upsert_discovered(self, uuid: str, vtype: str, ts_us: int, collector_id: str = None):
        if self.conn is None:
            return {
                "uuid": uuid,
                "vtype": vtype,
                "assigned_model": None,
                "model_settings_json": {},
                "enabled_for_scoring": False,
                "status": "discovered",
            }

        existing = self.get_tag(uuid)
        if existing:
            # keep original vtype stable
            return existing

        if self.count_tags() >= self.settings.learned_tags_max:
            raise RuntimeError("learned_tags_cap_reached")

        ts_dt = _ts_us_to_dt(ts_us)

        with self.conn.cursor() as cur:
            cur.execute(
                """
                insert into learned_tags (
                    uuid, vtype, collector_id, discovery_date,
                    first_seen_ts, last_seen_ts,
                    assigned_model, model_settings_json,
                    enabled_for_scoring, status, updated_at
                )
                values (
                    %s, %s, %s, now(),
                    %s, %s,
                    null, '{}'::jsonb,
                    false, 'discovered', now()
                )
                returning *
                """,
                (uuid, vtype, collector_id, ts_dt, ts_dt),
            )
            row = cur.fetchone()

            cur.execute(
                """
                insert into learned_tag_actions (uuid, action, payload_json)
                values (%s, %s, %s::jsonb)
                """,
                (
                    uuid,
                    "discover",
                    json.dumps({"uuid": uuid, "vtype": vtype, "collector_id": collector_id}),
                ),
            )

            return row

    def touch_seen(self, uuid: str, ts_us: int, value=None):
        if self.conn is None:
            return
        ts_dt = _ts_us_to_dt(ts_us)
        value_txt = None if value is None else str(value)[:500]

        with self.conn.cursor() as cur:
            cur.execute(
                """
                update learned_tags
                set last_seen_ts = %s,
                    last_value_text = %s,
                    updated_at = now()
                where uuid = %s
                """,
                (ts_dt, value_txt, uuid),
            )

    def list_tags(self, q: str = "", vtype: str = "all", status: str = "all", limit: int = 100):
        if self.conn is None:
            return []

        where = []
        params = []

        if q:
            where.append("uuid ilike %s")
            params.append(f"%{q}%")

        if vtype != "all":
            where.append("vtype = %s")
            params.append(vtype)

        if status != "all":
            where.append("status = %s")
            params.append(status)

        sql = """
            select uuid, vtype, collector_id, discovery_date, first_seen_ts, last_seen_ts,
                   assigned_model, model_settings_json, enabled_for_scoring, status,
                   notes, created_at, updated_at
            from learned_tags
        """
        if where:
            sql += " where " + " and ".join(where)

        sql += " order by last_seen_ts desc nulls last limit %s"
        params.append(limit)

        with self.conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()

    def assign_model(self, uuid: str, assigned_model: str, model_settings_json: dict, actor="ui", source="ui"):
        if self.conn is None:
            raise RuntimeError("Postgres not configured")

        with self.conn.cursor() as cur:
            cur.execute(
                """
                update learned_tags
                set assigned_model = %s,
                    model_settings_json = %s::jsonb,
                    status = case
                        when enabled_for_scoring then 'active'
                        else 'assigned'
                    end,
                    updated_at = now()
                where uuid = %s
                returning *
                """,
                (assigned_model, json.dumps(model_settings_json or {}), uuid),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError(f"uuid {uuid} not found")

            cur.execute(
                """
                insert into learned_tag_actions (uuid, action, payload_json, actor, source)
                values (%s, %s, %s::jsonb, %s, %s)
                """,
                (
                    uuid,
                    "assign_model",
                    json.dumps(
                        {
                            "assigned_model": assigned_model,
                            "model_settings_json": model_settings_json or {},
                        }
                    ),
                    actor,
                    source,
                ),
            )

            cur.execute(
                """
                insert into learned_tag_model_history
                    (uuid, vtype, assigned_model, model_settings_json, actor, source)
                values
                    (%s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    uuid,
                    row["vtype"],
                    assigned_model,
                    json.dumps(model_settings_json or {}),
                    actor,
                    source,
                ),
            )

            return row

    def set_enabled(self, uuid: str, enabled: bool, actor="ui", source="ui"):
        if self.conn is None:
            raise RuntimeError("Postgres not configured")

        with self.conn.cursor() as cur:
            cur.execute(
                """
                update learned_tags
                set enabled_for_scoring = %s,
                    status = case
                        when %s = true and assigned_model is not null then 'active'
                        when %s = false then 'disabled'
                        when assigned_model is not null then 'assigned'
                        else 'discovered'
                    end,
                    updated_at = now()
                where uuid = %s
                returning *
                """,
                (enabled, enabled, enabled, uuid),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError(f"uuid {uuid} not found")

            cur.execute(
                """
                insert into learned_tag_actions (uuid, action, payload_json, actor, source)
                values (%s, %s, %s::jsonb, %s, %s)
                """,
                (
                    uuid,
                    "set_enabled",
                    json.dumps({"enabled": enabled}),
                    actor,
                    source,
                ),
            )

            return row

    def list_model_history(self, uuid: str = "", limit: int = 100):
        if self.conn is None:
            return []

        with self.conn.cursor() as cur:
            if uuid:
                cur.execute(
                    """
                    select id, uuid, assigned_at, vtype, assigned_model,
                           model_settings_json, actor, source
                    from learned_tag_model_history
                    where uuid = %s
                    order by assigned_at desc, id desc
                    limit %s
                    """,
                    (uuid, limit),
                )
            else:
                cur.execute(
                    """
                    select id, uuid, assigned_at, vtype, assigned_model,
                           model_settings_json, actor, source
                    from learned_tag_model_history
                    order by assigned_at desc, id desc
                    limit %s
                    """,
                    (limit,),
                )
            return cur.fetchall()

    def get_model_history_item(self, history_id: int):
        if self.conn is None:
            raise RuntimeError("Postgres not configured")

        with self.conn.cursor() as cur:
            cur.execute(
                """
                select id, uuid, assigned_at, vtype, assigned_model,
                       model_settings_json, actor, source
                from learned_tag_model_history
                where id = %s
                """,
                (history_id,),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError(f"history_id {history_id} not found")
            return row