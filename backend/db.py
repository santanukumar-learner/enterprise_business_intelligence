import os
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import create_engine, String, Text, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, mapped_column, sessionmaker
from .config import database_url

def uid():
    return str(uuid4())

def now():
    return datetime.now(timezone.utc).isoformat()

if os.getenv('APP_ENV') == 'production' and not database_url:
    raise RuntimeError('DATABASE_URL is required in production; local disks may be ephemeral')
URL = database_url or 'sqlite:///./data/atlas.db'
if URL.startswith('postgres://'):
    URL = URL.replace('postgres://', 'postgresql+psycopg://', 1)
elif URL.startswith('postgresql://'):
    URL = URL.replace('postgresql://', 'postgresql+psycopg://', 1)
os.makedirs('data', exist_ok=True)
engine = create_engine(URL, connect_args={'check_same_thread': False} if URL.startswith('sqlite') else {'connect_timeout': 10}, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id = mapped_column(String, primary_key=True, default=uid)
    email = mapped_column(String, unique=True, nullable=False)
    name = mapped_column(String, nullable=False)
    password = mapped_column(String, nullable=False)

class Tenant(Base):
    __tablename__ = 'tenants'
    id = mapped_column(String, primary_key=True, default=uid)
    name = mapped_column(String, nullable=False)

class Membership(Base):
    __tablename__ = 'memberships'
    __table_args__ = (UniqueConstraint('user_id', 'tenant_id'),)
    id = mapped_column(String, primary_key=True, default=uid)
    user_id = mapped_column(ForeignKey('users.id'), nullable=False)
    tenant_id = mapped_column(ForeignKey('tenants.id'), nullable=False, index=True)
    role = mapped_column(String, nullable=False, default='viewer')

class Dataset(Base):
    __tablename__ = 'datasets'
    __table_args__ = (UniqueConstraint('tenant_id', 'table_name'),)
    id = mapped_column(String, primary_key=True, default=uid)
    tenant_id = mapped_column(ForeignKey('tenants.id'), nullable=False, index=True)
    name = mapped_column(String, nullable=False)
    table_name = mapped_column(String, nullable=False)
    columns = mapped_column(JSON, nullable=False)
    rows = mapped_column(JSON, nullable=False)
    created_at = mapped_column(String, default=now)

class Dashboard(Base):
    __tablename__ = 'dashboards'
    id = mapped_column(String, primary_key=True, default=uid)
    tenant_id = mapped_column(ForeignKey('tenants.id'), nullable=False, index=True)
    name = mapped_column(String, nullable=False)
    description = mapped_column(String, default='')
    widgets = mapped_column(JSON, default=list)
    created_at = mapped_column(String, default=now)

class Report(Base):
    __tablename__ = 'reports'
    id = mapped_column(String, primary_key=True, default=uid)
    tenant_id = mapped_column(ForeignKey('tenants.id'), nullable=False, index=True)
    name = mapped_column(String, nullable=False)
    sql = mapped_column(Text, nullable=False)
    status = mapped_column(String, default='queued')
    content = mapped_column(Text, nullable=True)
    error = mapped_column(Text, nullable=True)
    created_at = mapped_column(String, default=now)

class SavedQuery(Base):
    __tablename__ = 'saved_queries'
    id = mapped_column(String, primary_key=True, default=uid)
    tenant_id = mapped_column(ForeignKey('tenants.id'), nullable=False, index=True)
    name = mapped_column(String, nullable=False)
    sql = mapped_column(Text, nullable=False)
    created_at = mapped_column(String, default=now)

class Audit(Base):
    __tablename__ = 'audit'
    id = mapped_column(String, primary_key=True, default=uid)
    tenant_id = mapped_column(ForeignKey('tenants.id'), nullable=False, index=True)
    user_id = mapped_column(String, nullable=False)
    action = mapped_column(String, nullable=False)
    created_at = mapped_column(String, default=now)

def init_db():
    Base.metadata.create_all(engine)
