import os
import subprocess
import sys

import pytest

from app.db import Base, engine

NEEDED = ("NGAO_TEST_OWNER_URL", "NGAO_TEST_APP_URL", "NGAO_TEST_APP_PASSWORD")

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(name) for name in NEEDED),
    reason="set NGAO_TEST_OWNER_URL, NGAO_TEST_APP_URL and NGAO_TEST_APP_PASSWORD",
)


def run_script(module, **env):
    return subprocess.run(
        [sys.executable, "-m", module], capture_output=True, text=True,
        env={**os.environ, "DEMO_MODE": "true", **env},
    )


def test_the_runtime_role_and_the_owner_cannot_rewrite_the_audit_trail():
    owner, app_role, password = (os.environ[name] for name in NEEDED)
    try:
        hardened = run_script("scripts.harden_db", DATABASE_URL=owner, MIGRATION_DATABASE_URL=owner, APP_DB_PASSWORD=password)
        assert hardened.returncode == 0, hardened.stderr
        checked = run_script("scripts.verify_hardening", DATABASE_URL=app_role, MIGRATION_DATABASE_URL=owner)
        assert checked.returncode == 0, checked.stdout + checked.stderr
        assert "PASS" in checked.stdout and "ALLOWED" not in checked.stdout
        assert checked.stdout.count("BLOCKED") == 6
    finally:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
