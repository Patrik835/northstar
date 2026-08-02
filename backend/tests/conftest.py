import os

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-that-is-at-least-32-chars")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

