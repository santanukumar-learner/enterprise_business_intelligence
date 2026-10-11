import os
import tempfile
from pathlib import Path
temp_dir = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(temp_dir.name) / 'test.db').replace('\\', '/')
os.environ.pop('DATABASE_URL_POOLED', None)
os.environ['JWT_SECRET'] = 'test-only-secret-that-is-longer-than-thirty-two-characters'
os.environ.pop('REDIS_URL', None)
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.db import Session, Membership, User, engine
from sqlalchemy import select

@pytest.fixture(scope='module')
def client():
    with TestClient(app) as client:
        yield client
    engine.dispose()
    temp_dir.cleanup()

def account(client, name):
    r = client.post('/api/auth/register', json={'email':f'{name}@example.test','password':'StrongTestPassword123!','name':name,'company':name})
    assert r.status_code == 201, r.text
    h = {'Authorization':'Bearer '+r.json()['access_token']}
    workspace = client.get('/api/me', headers=h).json()['workspaces'][0]
    return {**h, 'X-Tenant-Id':workspace['id']}

def upload(client, headers, name='sales', csv=b'region,revenue\nEast,100\nWest,200\n'):
    return client.post('/api/datasets', headers=headers, data={'name':name}, files={'file':('sales.csv', csv, 'text/csv')})

def test_tenant_isolation_and_sql(client):
    a, b = account(client,'CompanyA'), account(client,'CompanyB')
    dataset = upload(client,a)
    assert dataset.status_code == 201
    dataset_id = dataset.json()['id']
    assert client.get('/api/datasets',headers=b).json() == []
    assert client.get('/api/datasets/'+dataset_id,headers=b).status_code == 404
    assert client.delete('/api/datasets/'+dataset_id,headers=b).status_code == 404
    assert client.get('/api/datasets',headers={**b,'X-Tenant-Id':a['X-Tenant-Id']}).status_code == 403
    assert client.post('/api/query',headers=b,json={'sql':'SELECT * FROM sales'}).status_code == 422
    r = client.post('/api/query',headers=a,json={'sql':'SELECT SUM(revenue) AS total FROM sales'})
    assert r.json()['rows'] == [[300]]
    for sql in ['DELETE FROM sales','DROP TABLE sales',"ATTACH DATABASE '/tmp/escape.db' AS x",'PRAGMA database_list','SELECT * FROM sqlite_master',"SELECT load_extension('bad')",'SELECT 1; SELECT 2']:
        assert client.post('/api/query',headers=a,json={'sql':sql}).status_code == 422, sql
    assert client.post('/api/query',headers=a,json={'sql':'SELECT COUNT(*) FROM sales'}).json()['rows'] == [[2]]
    sql = 'WITH RECURSIVE t(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM t) SELECT SUM(x) FROM t'
    assert client.post('/api/query',headers=a,json={'sql':sql}).status_code == 422

def test_viewer_rbac(client):
    owner, viewer = account(client,'Owner'), account(client,'Viewer')
    assert client.post('/api/members',headers=owner,json={'email':'viewer@example.test','role':'viewer'}).status_code == 200
    upload(client,owner)
    view = {**viewer,'X-Tenant-Id':owner['X-Tenant-Id']}
    assert len(client.get('/api/datasets',headers=view).json()) == 1
    assert client.post('/api/query',headers=view,json={'sql':'SELECT * FROM sales'}).status_code == 403
    assert upload(client,view).status_code == 403
    assert client.post('/api/dashboards',headers=view,json={'name':'Forbidden'}).status_code == 403
    assert client.post('/api/reports',headers=view,json={'name':'Forbidden','sql':'SELECT 1'}).status_code == 403
    assert client.get('/api/members',headers=view).status_code == 403
    assert client.post('/api/members',headers=view,json={'email':'owner@example.test','role':'admin'}).status_code == 403

def test_dashboard_report_and_saved_query(client):
    a, b = account(client,'Analytics'), account(client,'Other')
    upload(client,a)
    d = client.post('/api/dashboards',headers=a,json={'name':'Revenue','widgets':[{'title':'Revenue','type':'metric','sql':'SELECT SUM(revenue) FROM sales'}]})
    assert d.status_code == 201
    did = d.json()['id']
    assert client.get(f'/api/dashboards/{did}/data',headers=a).json()[0]['result']['rows'] == [[300]]
    assert client.get(f'/api/dashboards/{did}/data',headers=b).status_code == 404
    assert client.put(f'/api/dashboards/{did}',headers=b,json={'name':'Hijack'}).status_code == 404
    report = client.post('/api/reports',headers=a,json={'name':'Region sales','sql':'SELECT * FROM sales'})
    assert report.status_code == 202
    rid = report.json()['id']
    assert client.get('/api/reports',headers=a).json()[0]['status'] == 'complete'
    assert 'East,100' in client.get(f'/api/reports/{rid}/download',headers=a).text
    assert client.get(f'/api/reports/{rid}/download',headers=b).status_code == 404
    assert client.get('/api/reports',headers=b).json() == []
    assert client.post('/api/queries',headers=a,json={'name':'Totals','sql':'SELECT SUM(revenue) FROM sales'}).status_code == 201
    assert client.get('/api/queries',headers=b).json() == []

def test_upload_validation_and_formula_escape(client):
    h = account(client,'Validation')
    for content in [b'',b'x,x\n1,2',b'x,y\n1,2,3',b'x\n',b'1bad\n2']:
        assert upload(client,h,csv=content).status_code == 422
    assert upload(client,h,csv=b'label,amount\n=SUM(1),2\n').status_code == 201
    assert upload(client,h).status_code == 409
    assert upload(client,h,name='sqlite_bad').status_code == 422
    report=client.post('/api/reports',headers=h,json={'name':'safe','sql':'SELECT * FROM sales'}).json()
    text=client.get(f'/api/reports/{report["id"]}/download',headers=h).text
    assert "'=SUM(1)" in text

def test_authentication(client):
    assert client.get('/api/me').status_code == 401
    assert client.get('/api/me',headers={'Authorization':'Bearer invalid'}).status_code == 401
    assert client.post('/api/auth/login',json={'email':'no@example.test','password':'incorrect123'}).status_code == 401
    assert client.post('/api/auth/login',json={'email':'companya@example.test','password':'StrongTestPassword123!'}).status_code == 200
    assert client.post('/api/auth/register',json={'email':'companya@example.test','password':'StrongTestPassword123!','name':'Dup','company':'Dup'}).status_code == 409

def test_query_cache_is_tenant_scoped(client, monkeypatch):
    from backend.analytics import execute_query
    import redis
    cache_data = {}
    class FakeCache:
        def get(self, key):
            return cache_data.get(key)
        def setex(self, key, ttl, value):
            assert ttl == 60
            cache_data[key] = value
    monkeypatch.setattr(redis.Redis, 'from_url', lambda *a, **kw: FakeCache())
    a, b = account(client,'CacheA'), account(client,'CacheB')
    upload(client,a,csv=b'region,revenue\nEast,100')
    upload(client,b,csv=b'region,revenue\nEast,999')
    monkeypatch.setenv('REDIS_URL','redis://test:6379/0')
    with Session() as db:
        first = execute_query(db, a['X-Tenant-Id'], 'SELECT SUM(revenue) FROM sales')
        hit = execute_query(db, a['X-Tenant-Id'], 'SELECT SUM(revenue) FROM sales')
        other = execute_query(db, b['X-Tenant-Id'], 'SELECT SUM(revenue) FROM sales')
        assert first['rows'] == hit['rows'] == [[100]]
        assert not first['cached'] and hit['cached']
        assert other['rows'] == [[999]] and not other['cached']

def test_result_limits_and_nonfinite_values(client):
    h = account(client,'Bounds')
    csv_data = ('n\n'+'\n'.join(str(i) for i in range(1005))).encode()
    assert upload(client,h,csv=csv_data).status_code == 201
    r = client.post('/api/query',headers=h,json={'sql':'SELECT * FROM sales'})
    assert len(r.json()['rows']) == 1000 and r.json()['truncated']
    assert client.post('/api/query',headers=h,json={'sql':'SELECT 1e999 AS too_large'}).json()['rows'] == [[None]]

def test_csv_nonfinite_and_filename_query(client):
    h = account(client,'CsvEdges')
    response = client.post('/api/datasets', headers=h, files={'file': ('sample-sales.csv', b'region,revenue\nEast,100\nWest,200\n', 'text/csv')})
    assert response.status_code == 201
    table = response.json()['table_name']
    assert table == 'sample_sales'
    assert client.post('/api/query',headers=h,json={'sql':f'SELECT SUM(revenue) FROM "{table}"'}).json()['rows'] == [[300]]
    response = upload(client,h,name='special',csv=b'label,value\nA,NaN\nB,Infinity\n')
    assert response.status_code == 201
    assert response.json()['columns'][1]['type'] == 'TEXT'
    result = client.post('/api/query',headers=h,json={'sql':'SELECT * FROM special'})
    assert result.status_code == 200 and result.json()['rows'] == [['A','NaN'],['B','Infinity']]
    assert upload(client,h,name='malformed',csv=b'label,value\nA,"unclosed\n').status_code == 422

def test_demo_not_advertised_when_unseeded(client):
    assert client.get('/api/auth/options').json() == {'demo_available': False}
