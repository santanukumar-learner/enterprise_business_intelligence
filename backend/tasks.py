import csv
import io
import os
from celery import Celery
from .db import Session, Report
from .analytics import execute_query

celery_app = Celery('atlas', broker=os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
celery_app.conf.update(task_serializer='json', accept_content=['json'], task_time_limit=30, worker_prefetch_multiplier=1, task_acks_late=True, task_reject_on_worker_lost=True)

@celery_app.task(name='atlas.generate_report')
def generate_report(report_id, tenant_id):
    with Session() as db:
        report = db.get(Report, report_id)
        if not report or report.tenant_id != tenant_id or report.status == 'complete':
            return
        report.status = 'processing'
        db.commit()
        try:
            result = execute_query(db, tenant_id, report.sql)
            output = io.StringIO()
            writer = csv.writer(output)
            def safe(value):
                # Prevent CSV formula execution in spreadsheet applications.
                return "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value
            writer.writerow([safe(c) for c in result['columns']])
            writer.writerows([[safe(v) for v in row] for row in result['rows']])
            report.content = output.getvalue()
            report.status = 'complete'
        except Exception as exc:
            report.status = 'failed'
            report.error = str(exc)
        db.commit()
