"""Verify PostgreSQL, Redis caching, and Celery inside the running API container.

Run: docker compose exec -T api python - < scripts/smoke-stack.py
Creates and removes only its own temporary workspace and report.
"""
import csv
import io
import os
import time
from uuid import uuid4

import redis
from sqlalchemy import text
from backend.db import Session, Tenant, Report, engine
from backend.analytics import execute_query
from backend.tasks import generate_report

assert engine.dialect.name == 'postgresql', 'This check expects the Docker PostgreSQL stack.'
cache = redis.Redis.from_url(os.environ['REDIS_URL'])
assert cache.ping(), 'Redis is not reachable.'
workspace_id = str(uuid4())
report_id = str(uuid4())
try:
    with Session() as db:
        assert db.execute(text('SELECT 1')).scalar() == 1
        db.add(Tenant(id=workspace_id, name='Temporary stack verification'))
        db.commit()
        first = execute_query(db, workspace_id, 'SELECT 42 AS answer')
        second = execute_query(db, workspace_id, 'SELECT 42 AS answer')
        assert first['rows'] == [[42]] and not first['cached']
        assert second['rows'] == [[42]] and second['cached']
        db.add(Report(id=report_id, tenant_id=workspace_id, name='Temporary verification', sql='SELECT 42 AS answer'))
        db.commit()
    generate_report.apply_async(args=[report_id, workspace_id], retry=False)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with Session() as db:
            report = db.get(Report, report_id)
            assert report.status != 'failed', report.error
            if report.status == 'complete':
                assert list(csv.DictReader(io.StringIO(report.content))) == [{'answer': '42'}]
                print('PASS: PostgreSQL, Redis cache hit, Celery report generation')
                break
        time.sleep(.5)
    else:
        raise RuntimeError('The Celery worker did not finish the report within 20 seconds.')
finally:
    with Session() as db:
        report = db.get(Report, report_id)
        if report:
            db.delete(report)
            db.flush()
        workspace = db.get(Tenant, workspace_id)
        if workspace:
            db.delete(workspace)
        db.commit()
    engine.dispose()
