from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from oilmart.db import initialize, make_engine
from oilmart.models import User
from oilmart.security import authenticate, change_password, verify_password
from oilmart.seed import seed


def test_login_locks_after_five_failures_and_unlocks_after_timeout():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for _ in range(4):
            user, message = authenticate(session, "admin", "wrong", now=now)
            assert user is None
            assert message == "Invalid username or password"
        user, message = authenticate(session, "admin", "wrong", now=now)
        assert user is None
        assert "locked" in message
        user, message = authenticate(session, "admin", "ChangeMe123!", now=now)
        assert user is None
        assert "locked until" in message
        user, message = authenticate(session, "admin", "ChangeMe123!", now=now + timedelta(minutes=16))
        assert user is not None


def test_temporary_admin_password_must_be_changed():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        user = session.scalar(select(User).where(User.username == "admin"))
        assert user.must_change_password is True
        change_password(session, user, "ChangeMe123!", "StrongPassword2026")
        assert verify_password("StrongPassword2026", user.password_hash)
        assert user.must_change_password is False


def test_five_character_password_is_accepted_but_four_is_rejected():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        user = session.scalar(select(User).where(User.username == "admin"))
        try:
            change_password(session, user, "ChangeMe123!", "Ab1x")
            assert False, "four-character password was accepted"
        except ValueError as exc:
            assert "at least 5" in str(exc)
        change_password(session, user, "ChangeMe123!", "Abc12")
        assert verify_password("Abc12", user.password_hash)
