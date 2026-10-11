"""Load local configuration without overriding platform or test environment values."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Explicit process configuration takes precedence over values from local .env.
_explicit_database_url = os.getenv('DATABASE_URL_POOLED') or os.getenv('DATABASE_URL')
load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=False)
database_url = _explicit_database_url or os.getenv('DATABASE_URL_POOLED') or os.getenv('DATABASE_URL')
