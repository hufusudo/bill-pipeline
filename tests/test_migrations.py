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


def test_migration_failure_keeps_legacy_schema_and_backup(tmp_path,monkeypatch):
    import bill_pipeline.migrations as migration
    path=tmp_path/'failure.db'
    c=sqlite3.connect(path);c.executescript(SCHEMA)
    monkeypatch.setattr(migration,'DDL',migration.DDL+['THIS IS INVALID SQL'])
    with pytest.raises(sqlite3.OperationalError):migration.migrate(c,path)
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_version'").fetchone()
    assert 'exported_at' not in [r[1] for r in c.execute('PRAGMA table_info(imports)')]
    assert len(list((tmp_path/'backups').glob('*.db')))==1
    c.close()


def test_backup_failure_prevents_any_schema_change(tmp_path,monkeypatch):
    import bill_pipeline.migrations as migration
    path=tmp_path/'failure.db';c=sqlite3.connect(path);c.executescript(SCHEMA)
    def fail(*args):raise OSError('simulated full disk')
    monkeypatch.setattr(migration,'backup_database',fail)
    with pytest.raises(OSError):migration.migrate(c,path)
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_version'").fetchone()
    c.close()


def test_version_one_upgrades_without_duplicate_base_tables(tmp_path):
    path=tmp_path/'v1.db';c=connect(path)
    with c:
        for table in ('evidence','messages','conversations','runtime_instances','review_decisions'):c.execute('DROP TABLE '+table)
        c.execute('UPDATE schema_version SET version=1')
    c.close();c=connect(path)
    assert c.execute('SELECT version FROM schema_version').fetchone()[0]==3
    assert c.execute('SELECT count(*) FROM conversations').fetchone()[0]==0
    c.close()
