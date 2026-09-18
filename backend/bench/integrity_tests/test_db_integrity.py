"""Database Integrity and Data validation testing."""

import pytest
from sqlalchemy.exc import IntegrityError
from autoviz.core.database import get_db
from autoviz.models.dashboard import Dashboard

def test_db_foreign_key_violation(api_db):
    """Ensure inserting a Dashboard with a non-existent user_id fails cleanly at the DB layer."""
    # Obtain a session from the engine (api_db sets up the sqlite engine)
    # get_db() returns a generator
    db = next(get_db())
    
    # Enforce SQLite foreign keys for this connection
    from sqlalchemy import text
    db.execute(text("PRAGMA foreign_keys=ON"))
    
    # Attempt to insert a dashboard with a junk user_id
    bad_dashboard = Dashboard(user_id="user_that_does_not_exist", name="Hack Dashboard")
    db.add(bad_dashboard)
    
    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    
    # Must rollback the failed transaction to continue using the session
    db.rollback()
    assert "FOREIGN KEY constraint failed" in str(exc_info.value)

def test_db_not_null_violation(api_db):
    """Ensure inserting a Dashboard without a required field (name) raises IntegrityError."""
    db = next(get_db())
    
    # Attempt to insert without 'name'
    bad_dashboard = Dashboard(user_id="some_id") # Missing 'name'
    db.add(bad_dashboard)
    
    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    
    db.rollback()
    assert "NOT NULL constraint failed" in str(exc_info.value)
