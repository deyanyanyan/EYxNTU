"""Test config. Unit tests here do not need Postgres; API tests that do are marked `integration`."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://lms:test@localhost:5432/lms_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-for-validation-1234")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("DATA_DIR", os.path.join(os.path.dirname(__file__), "_data"))
