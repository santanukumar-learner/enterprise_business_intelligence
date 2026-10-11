"""Bounded read-only SQL over a tenant-only snapshot. No database credentials exposed."""
import csv
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import time
from sqlalchemy import select
from .db import Dataset

MAX_ROWS = 20000
MAX_RESULT = 1000

def identifier(value):
    return re.sub(r'[^a-z0-9_]', '_', value.lower()).strip('_')[:60]

def parse_csv(content):
    if len(content) > 10 * 1024 * 1024:
        raise ValueError('Maximum upload size is 10 MB.')
    try:
        reader = csv.reader(io.StringIO(content.decode('utf-8-sig')), strict=True)
        header = next(reader)
    except (UnicodeError, StopIteration):
        raise ValueError('Upload a UTF-8 CSV with a header row.')
    columns = [identifier(x) for x in header]
    if not columns or len(columns) > 50 or any(not x or not re.match(r'^[a-z_]', x) for x in columns):
        raise ValueError('Use 1–50 named columns beginning with a letter.')
    if len(set(columns)) != len(columns):
        raise ValueError('Column names must be unique after normalization.')
    rows = []
    for row in reader:
        if not row:
            continue
        if len(row) != len(columns):
            raise ValueError('Every row must have the same number of columns.')
        if len(rows) >= MAX_ROWS:
            raise ValueError('Maximum dataset size is 20,000 rows.')
        rows.append(row)
    if not rows:
        raise ValueError('The CSV has no data rows.')
    types = []
    for index in range(len(columns)):
        values = [r[index] for r in rows if r[index] != '']
        try:
            for v in values:
                if not math.isfinite(float(v)):
                    raise ValueError('Non-finite number')
            numeric = bool(values)
        except ValueError:
            numeric = False
        types.append('REAL' if numeric else 'TEXT')
        for row in rows:
            row[index] = (float(row[index]) if row[index] else None) if numeric else row[index]
    return [{'name': c, 'type': t} for c, t in zip(columns, types)], rows

def execute_query(db, tenant_id, sql, use_cache=True):
    if not sql.strip() or len(sql) > 10000:
        raise ValueError('Enter a SELECT query under 10,000 characters.')
    datasets = list(db.scalars(select(Dataset).where(Dataset.tenant_id == tenant_id)))
    fingerprint = [(d.id, d.created_at) for d in datasets]
    cache_key = 'query:' + hashlib.sha256(json.dumps([tenant_id, fingerprint, sql]).encode()).hexdigest()
    cache = None
    if os.getenv('REDIS_URL') and use_cache:
        import redis
        cache = redis.Redis.from_url(os.environ['REDIS_URL'], socket_connect_timeout=1, socket_timeout=1)
        try:
            hit = cache.get(cache_key)
            if hit:
                result = json.loads(hit)
                result['cached'] = True
                return result
        except redis.RedisError:
            cache = None
    started = time.monotonic()
    conn = sqlite3.connect(':memory:')
    try:
        for dataset in datasets:
            columns = ', '.join(f'"{c["name"]}" {c["type"]}' for c in dataset.columns)
            conn.execute(f'CREATE TABLE "{dataset.table_name}" ({columns})')
            conn.executemany(f'INSERT INTO "{dataset.table_name}" VALUES ({",".join("?" for _ in dataset.columns)})', dataset.rows)
        conn.commit()
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
        # No schema inspection, PRAGMA, ATTACH, writes, extension loading, or filesystem access.
        def authorize(action, a, b, database, trigger):
            if action == sqlite3.SQLITE_READ and a not in {d.table_name for d in datasets}:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and (b or '').lower() in {'load_extension', 'readfile', 'writefile'}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
        conn.set_authorizer(authorize)
        conn.set_progress_handler(lambda: int(time.monotonic() - started > 3), 1000)
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1000000)
        cursor = conn.execute(sql)
        if cursor.description is None:
            raise ValueError('Only read-only queries are permitted.')
        rows = cursor.fetchmany(MAX_RESULT + 1)
        cleaned = [[None if isinstance(v, float) and not math.isfinite(v) else v for v in row] for row in rows[:MAX_RESULT]]
        result = {'columns': [c[0] for c in cursor.description], 'rows': cleaned, 'truncated': len(rows) > MAX_RESULT, 'elapsed_ms': round((time.monotonic() - started) * 1000, 1), 'cached': False}
        if cache:
            try:
                cache.setex(cache_key, 60, json.dumps(result))
            except Exception:
                pass
        return result
    except sqlite3.Error as exc:
        raise ValueError(f'Query could not run: {exc}') from exc
    finally:
        conn.close()
