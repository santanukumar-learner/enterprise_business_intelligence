import os
import asyncio
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header, BackgroundTasks
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from .db import Session, init_db, User, Tenant, Membership, Dataset, Dashboard, Report, SavedQuery, Audit
from .security import token, decode, hash_password, verify_password
from .analytics import parse_csv, identifier, execute_query
import csv
from .tasks import generate_report

@asynccontextmanager
async def lifespan(app):
    init_db()
    # Free hosting may restart. Recover unfinished local report jobs from the DB.
    async def recover_reports():
        with Session() as db:
            pending = [(r.id, r.tenant_id) for r in db.scalars(select(Report).where(Report.status.in_(['queued', 'processing'])))]
        for report_id, tenant_id in pending:
            await asyncio.to_thread(generate_report, report_id, tenant_id)
    recovery = None
    if not os.getenv('REDIS_URL'):
        recovery = asyncio.create_task(recover_reports())
    yield
    if recovery:
        await recovery

app = FastAPI(title='Atlas Business Intelligence', version='1.0.0', lifespan=lifespan)

def database():
    with Session() as db:
        yield db

def current_user(authorization: str = Header(default=''), db=Depends(database)):
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Sign in to continue.')
    user = db.get(User, decode(authorization[7:]))
    if not user:
        raise HTTPException(401, 'Account no longer exists.')
    return user

def scope(x_tenant_id: str = Header(default=''), user=Depends(current_user), db=Depends(database)):
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == x_tenant_id))
    if not membership:
        raise HTTPException(403, 'You do not have access to this workspace.')
    return membership

def editor(member):
    if member.role not in ('owner', 'admin', 'analyst'):
        raise HTTPException(403, 'An analyst or administrator role is required.')

def administrator(member):
    if member.role not in ('owner', 'admin'):
        raise HTTPException(403, 'An administrator role is required.')

def owned(db, model, item_id, member):
    item = db.scalar(select(model).where(model.id == item_id, model.tenant_id == member.tenant_id))
    if item is None:
        raise HTTPException(404, 'Item not found in this workspace.')
    return item

def audit(db, member, action):
    db.add(Audit(tenant_id=member.tenant_id, user_id=member.user_id, action=action))

def public(item, fields):
    return {f: getattr(item, f) for f in fields.split()}

class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=10, max_length=128)

class Registration(Credentials):
    name: str = Field(min_length=1, max_length=100)
    company: str = Field(min_length=1, max_length=100)

class WorkspaceInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)

class QueryInput(BaseModel):
    sql: str = Field(min_length=1, max_length=10000)

class SavedInput(QueryInput):
    name: str = Field(min_length=1, max_length=100)

class Widget(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    sql: str = Field(min_length=1, max_length=10000)
    type: Literal['bar', 'line', 'table', 'metric'] = 'bar'

class DashboardInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=300)
    widgets: list[Widget] = Field(default_factory=list, max_length=12)

class MemberInput(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: Literal['admin', 'analyst', 'viewer'] = 'viewer'

_attempts = defaultdict(deque)
_attempt_lock = threading.Lock()
def login_limit(email):
    # Redis is shared across API replicas. Local mode uses a process-local limiter.
    if os.getenv('REDIS_URL'):
        import redis, hashlib
        cache = redis.Redis.from_url(os.environ['REDIS_URL'], socket_timeout=1, socket_connect_timeout=1)
        key = 'login:' + hashlib.sha256(email.encode()).hexdigest()
        try:
            count = cache.incr(key)
            if count == 1:
                cache.expire(key, 300)
            if count > 10:
                raise HTTPException(429, 'Too many attempts. Try again in five minutes.')
            return
        except redis.RedisError:
            pass
    with _attempt_lock:
        attempts = _attempts[email]
        while attempts and attempts[0] < time.monotonic() - 300:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, 'Too many attempts. Try again in five minutes.')
        attempts.append(time.monotonic())

@app.get('/api/health')
def health(db=Depends(database)):
    db.execute(select(1))
    return {'status': 'ok', 'database': 'postgresql' if db.bind.dialect.name == 'postgresql' else 'sqlite', 'jobs': 'celery' if os.getenv('REDIS_URL') else 'local-background'}

@app.post('/api/auth/register', status_code=201)
def register(body: Registration, db=Depends(database)):
    email = body.email.strip().lower()
    if '@' not in email:
        raise HTTPException(422, 'Enter a valid email address.')
    login_limit(email)
    user = User(email=email, name=body.name, password=hash_password(body.password))
    tenant = Tenant(name=body.company)
    db.add_all([user, tenant])
    try:
        db.flush()
        db.add(Membership(user_id=user.id, tenant_id=tenant.id, role='owner'))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'This email already has an account.')
    return {'access_token': token(user.id)}

@app.post('/api/auth/login')
def login(body: Credentials, db=Depends(database)):
    email = body.email.strip().lower()
    login_limit(email)
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(body.password, user.password):
        raise HTTPException(401, 'Email or password is incorrect.')
    return {'access_token': token(user.id)}

@app.get('/api/me')
def me(user=Depends(current_user), db=Depends(database)):
    memberships = db.execute(select(Membership, Tenant).join(Tenant, Tenant.id == Membership.tenant_id).where(Membership.user_id == user.id)).all()
    return {'user': public(user, 'id email name'), 'workspaces': [{'id': t.id, 'name': t.name, 'role': m.role} for m, t in memberships]}

@app.post('/api/workspaces', status_code=201)
def create_workspace(body: WorkspaceInput, user=Depends(current_user), db=Depends(database)):
    tenant = Tenant(name=body.name)
    db.add(tenant)
    db.flush()
    db.add(Membership(user_id=user.id, tenant_id=tenant.id, role='owner'))
    db.commit()
    return public(tenant, 'id name')

@app.get('/api/datasets')
def datasets(member=Depends(scope), db=Depends(database)):
    items = db.scalars(select(Dataset).where(Dataset.tenant_id == member.tenant_id).order_by(Dataset.created_at.desc()))
    return [{**public(d, 'id name table_name columns created_at'), 'row_count': len(d.rows)} for d in items]

@app.post('/api/datasets', status_code=201)
async def upload(file: UploadFile = File(...), name: str = Form(default=''), member=Depends(scope), db=Depends(database)):
    editor(member)
    content = await file.read(10 * 1024 * 1024 + 1)
    try:
        columns, rows = parse_csv(content)
    except (ValueError, csv.Error) as exc:
        raise HTTPException(422, str(exc))
    table_name = identifier(name or Path(file.filename or 'dataset').stem)
    if not table_name or not table_name[0].isalpha() or table_name.startswith('sqlite_'):
        raise HTTPException(422, 'Dataset name must begin with a letter and cannot start with sqlite_.')
    existing = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.tenant_id == member.tenant_id))
    if existing >= 20:
        raise HTTPException(422, 'This workspace has reached the 20 dataset limit.')
    item = Dataset(tenant_id=member.tenant_id, name=name or file.filename, table_name=table_name, columns=columns, rows=rows)
    db.add(item)
    audit(db, member, f'Uploaded {table_name} ({len(rows)} rows)')
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'A dataset with this table name already exists.')
    return {**public(item, 'id name table_name columns'), 'row_count': len(rows)}

@app.get('/api/datasets/{item_id}')
def preview(item_id: str, member=Depends(scope), db=Depends(database)):
    item = owned(db, Dataset, item_id, member)
    return {**public(item, 'id name table_name columns'), 'rows': item.rows[:100], 'row_count': len(item.rows)}

@app.delete('/api/datasets/{item_id}', status_code=204)
def delete_dataset(item_id: str, member=Depends(scope), db=Depends(database)):
    editor(member)
    item = owned(db, Dataset, item_id, member)
    audit(db, member, f'Deleted dataset {item.table_name}')
    db.delete(item)
    db.commit()

@app.post('/api/query')
def query(body: QueryInput, member=Depends(scope), db=Depends(database)):
    editor(member)
    try:
        result = execute_query(db, member.tenant_id, body.sql)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit(db, member, 'Executed SQL query')
    db.commit()
    return result

@app.get('/api/queries')
def saved_queries(member=Depends(scope), db=Depends(database)):
    return [public(q, 'id name sql created_at') for q in db.scalars(select(SavedQuery).where(SavedQuery.tenant_id == member.tenant_id))]

@app.post('/api/queries', status_code=201)
def save_query(body: SavedInput, member=Depends(scope), db=Depends(database)):
    editor(member)
    item = SavedQuery(tenant_id=member.tenant_id, **body.model_dump())
    db.add(item)
    audit(db, member, f'Saved query {item.name}')
    db.commit()
    return public(item, 'id name sql')

@app.get('/api/dashboards')
def dashboards(member=Depends(scope), db=Depends(database)):
    return [public(d, 'id name description widgets created_at') for d in db.scalars(select(Dashboard).where(Dashboard.tenant_id == member.tenant_id).order_by(Dashboard.created_at))]

def validate_widgets(body, db, member):
    for widget in body.widgets:
        try:
            execute_query(db, member.tenant_id, widget.sql)
        except ValueError as exc:
            raise HTTPException(422, f'{widget.title}: {exc}')

@app.post('/api/dashboards', status_code=201)
def create_dashboard(body: DashboardInput, member=Depends(scope), db=Depends(database)):
    editor(member)
    validate_widgets(body, db, member)
    item = Dashboard(tenant_id=member.tenant_id, **body.model_dump())
    db.add(item)
    audit(db, member, f'Created dashboard {item.name}')
    db.commit()
    return public(item, 'id name description widgets created_at')

@app.put('/api/dashboards/{item_id}')
def update_dashboard(item_id: str, body: DashboardInput, member=Depends(scope), db=Depends(database)):
    editor(member)
    item = owned(db, Dashboard, item_id, member)
    validate_widgets(body, db, member)
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    audit(db, member, f'Updated dashboard {item.name}')
    db.commit()
    return public(item, 'id name description widgets created_at')

@app.get('/api/dashboards/{item_id}/data')
def dashboard_data(item_id: str, member=Depends(scope), db=Depends(database)):
    item = owned(db, Dashboard, item_id, member)
    widgets = []
    for widget in item.widgets:
        try:
            widgets.append({**widget, 'result': execute_query(db, member.tenant_id, widget['sql'])})
        except ValueError as exc:
            widgets.append({**widget, 'error': str(exc)})
    return widgets

@app.get('/api/reports')
def reports(member=Depends(scope), db=Depends(database)):
    return [public(r, 'id name sql status error created_at') for r in db.scalars(select(Report).where(Report.tenant_id == member.tenant_id).order_by(Report.created_at.desc()))]

@app.post('/api/reports', status_code=202)
def create_report(body: SavedInput, background: BackgroundTasks, member=Depends(scope), db=Depends(database)):
    editor(member)
    try:
        execute_query(db, member.tenant_id, body.sql)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    item = Report(tenant_id=member.tenant_id, **body.model_dump())
    db.add(item)
    audit(db, member, f'Requested report {item.name}')
    db.commit()
    if os.getenv('REDIS_URL'):
        try:
            generate_report.apply_async(args=[item.id, member.tenant_id], retry=False)
        except Exception:
            item.status = 'failed'
            item.error = 'Report queue unavailable. Please retry later.'
            db.commit()
            raise HTTPException(503, item.error)
    else:
        background.add_task(generate_report, item.id, member.tenant_id)
    return public(item, 'id name status created_at')

@app.get('/api/reports/{item_id}/download')
def download(item_id: str, member=Depends(scope), db=Depends(database)):
    item = owned(db, Report, item_id, member)
    if item.status != 'complete':
        raise HTTPException(409, 'This report is not ready to download.')
    return Response(item.content, media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="{identifier(item.name) or "report"}.csv"'})

@app.get('/api/members')
def members(member=Depends(scope), db=Depends(database)):
    administrator(member)
    rows = db.execute(select(Membership, User).join(User, Membership.user_id == User.id).where(Membership.tenant_id == member.tenant_id))
    return [{**public(u, 'id name email'), 'role': m.role} for m, u in rows]

@app.post('/api/members')
def add_member(body: MemberInput, member=Depends(scope), db=Depends(database)):
    administrator(member)
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user:
        raise HTTPException(404, 'This user must create an account first.')
    existing = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == member.tenant_id))
    if existing and (existing.role == 'owner' or existing.user_id == member.user_id):
        raise HTTPException(422, 'The owner and your own role cannot be changed here.')
    if existing:
        existing.role = body.role
    else:
        db.add(Membership(user_id=user.id, tenant_id=member.tenant_id, role=body.role))
    audit(db, member, f'Assigned {body.role} access to {user.email}')
    db.commit()
    return {'status': 'updated'}

@app.get('/api/audit')
def activity(member=Depends(scope), db=Depends(database)):
    return [public(a, 'id action created_at') for a in db.scalars(select(Audit).where(Audit.tenant_id == member.tenant_id).order_by(Audit.created_at.desc()).limit(30))]

STATIC = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
if STATIC.exists():
    app.mount('/assets', StaticFiles(directory=STATIC / 'assets'), name='assets')
    @app.get('/')
    def index():
        return FileResponse(STATIC / 'index.html')
