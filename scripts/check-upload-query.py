"""Exercise actual HTTP upload, SQL, dashboard, and Celery report endpoints.

Pipe this script into the Docker API container; only its temporary data is removed.
"""
import csv
import io
import secrets
import time
from uuid import uuid4
import httpx
from sqlalchemy import delete
from backend.db import Session, User, Tenant, Membership, Dataset, Dashboard, SavedQuery, Report, Audit

user_id = tenant_id = None
client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=15)
try:
    registration = client.post('/api/auth/register', json={'email': f'check-{uuid4()}@example.test', 'password': secrets.token_hex(16), 'name': 'Temporary verification', 'company': 'Temporary verification'})
    registration.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + registration.json()['access_token']
    profile = client.get('/api/me').json()
    user_id, tenant_id = profile['user']['id'], profile['workspaces'][0]['id']
    client.headers['X-Tenant-Id'] = tenant_id
    upload = client.post('/api/datasets', files={'file': ('sample-sales.csv', b'month,region,revenue\n2026-01,East,100\n2026-02,West,200\n', 'text/csv')})
    upload.raise_for_status()
    table = upload.json()['table_name']
    assert table == 'sample_sales' and upload.json()['row_count'] == 2
    sql = f'SELECT SUM(revenue) AS revenue FROM "{table}"'
    query = client.post('/api/query', json={'sql': sql})
    query.raise_for_status()
    assert query.json()['rows'] == [[300]]
    assert client.post('/api/query', json={'sql': sql}).json()['cached']
    for _ in range(2):
        overflow = client.post('/api/query', json={'sql': 'SELECT 1e999 AS overflow'})
        overflow.raise_for_status()
        assert overflow.json()['rows'] == [[None]]
    special = client.post('/api/datasets', data={'name': 'special'}, files={'file': ('special.csv', b'label,value\nA,NaN\nB,Infinity\n', 'text/csv')})
    special.raise_for_status()
    assert special.json()['columns'][1]['type'] == 'TEXT'
    assert client.post('/api/query', json={'sql': 'SELECT * FROM special'}).json()['rows'] == [['A', 'NaN'], ['B', 'Infinity']]
    malformed = client.post('/api/datasets', data={'name': 'malformed'}, files={'file': ('malformed.csv', b'label,value\nA,"unclosed\n', 'text/csv')})
    assert malformed.status_code == 422
    dashboard = client.post('/api/dashboards', json={'name': 'Verification', 'widgets': [{'title': 'Revenue', 'type': 'metric', 'sql': sql}]})
    dashboard.raise_for_status()
    assert client.get(f'/api/dashboards/{dashboard.json()["id"]}/data').json()[0]['result']['rows'] == [[300]]
    report = client.post('/api/reports', json={'name': 'Verification', 'sql': sql})
    report.raise_for_status()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        download = client.get(f'/api/reports/{report.json()["id"]}/download')
        if download.status_code == 200:
            assert float(list(csv.DictReader(io.StringIO(download.text)))[0]['revenue']) == 300
            break
        time.sleep(.5)
    else:
        raise RuntimeError('Report did not become available.')
    print('PASS: HTTP CSV upload, inferred table name, aggregate SQL, overflow/cache handling, malformed CSV validation, dashboard, Celery report download')
finally:
    client.close()
    if tenant_id:
        with Session() as db:
            for model in [Audit, Report, SavedQuery, Dashboard, Dataset, Membership]:
                db.execute(delete(model).where(model.tenant_id == tenant_id))
            db.execute(delete(Tenant).where(Tenant.id == tenant_id))
            db.execute(delete(User).where(User.id == user_id))
            db.commit()
