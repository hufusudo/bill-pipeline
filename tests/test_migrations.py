import sqlite3
import pytest
from bill_pipeline.db import SCHEMA, connect


def test_upgrade_backs_up_legacy_and_is_idempotent(tmp_path):
    path = tmp_path / 'legacy.db'
    old = sqlite3.connect(path)
    old.executescript(SCHEMA)
    old.close()
    conn = connect(path)
    assert conn.execute('SELECT version FROM schema_version').fetchone()[0] >= 1
    backups = list((tmp_path / 'backups').glob('*.db'))
    assert len(backups) == 1
    backup = sqlite3.connect(backups[0])
    assert not backup.execute("SELECT name FROM sqlite_master WHERE name='schema_version'").fetchall()
    backup.close()
    conn.close()
    connect(path).close()
    assert len(list((tmp_path / 'backups').glob('*.db'))) == 1


def test_revision_rolls_back():
    from bill_pipeline.migrations import data_revision, bump_revision
    conn = connect(':memory:')
    before = data_revision(conn)
    with pytest.raises(RuntimeError):
        with conn:
            bump_revision(conn)
            raise RuntimeError()
    assert data_revision(conn) == before
