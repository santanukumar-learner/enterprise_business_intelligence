import base64
import hashlib
import hmac
import os
import secrets
import time
import jwt
from fastapi import HTTPException
from . import config  # Load .env before reading authentication settings.

SECRET = os.getenv('JWT_SECRET')
if os.getenv('APP_ENV') == 'production' and SECRET and len(SECRET) < 32:
    raise RuntimeError('JWT_SECRET must contain at least 32 characters in production')
if not SECRET:
    if os.getenv('APP_ENV') == 'production':
        raise RuntimeError('JWT_SECRET is required in production')
    # Stable local key; never tracked or reused for production.
    os.makedirs('data', exist_ok=True)
    key_path = 'data/local-secret'
    if not os.path.exists(key_path):
        with open(key_path, 'w') as f:
            f.write(secrets.token_hex(32))
    with open(key_path) as f:
        SECRET = f.read().strip()

def hash_password(password):
    salt = secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000)
    return base64.b64encode(salt + value).decode()

def verify_password(password, stored):
    try:
        raw = base64.b64decode(stored)
        value = hashlib.pbkdf2_hmac('sha256', password.encode(), raw[:16], 600000)
        return hmac.compare_digest(raw[16:], value)
    except (ValueError, TypeError):
        return False

def token(user_id):
    return jwt.encode({'sub': user_id, 'exp': int(time.time()) + 28800, 'iat': int(time.time()), 'iss': 'atlas'}, SECRET, algorithm='HS256')

def decode(value):
    try:
        return jwt.decode(value, SECRET, algorithms=['HS256'], issuer='atlas', options={'require': ['sub', 'exp', 'iat']})['sub']
    except jwt.PyJWTError:
        raise HTTPException(401, 'Session expired. Please sign in again.')
