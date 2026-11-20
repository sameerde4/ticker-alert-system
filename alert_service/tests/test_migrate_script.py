"""Deploy migrator must apply each SQL file once (003 deletes all alerts)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATE = ROOT / "deploy" / "migrate.sh"


def test_migrate_script_tracks_applied_filenames():
    text = MIGRATE.read_text(encoding="utf-8")
    assert "schema_migrations" in text
    assert "already applied" in text
    assert "ON CONFLICT DO NOTHING" in text
    assert "DELETE FROM alerts" not in text
    assert 'for f in /migrations/*.sql' in text
    assert "basename" in text
