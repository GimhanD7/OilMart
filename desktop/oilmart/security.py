import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .models import ActivityLog, User


def hash_password(password: str, *, iterations: int = 600_000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(raw_iterations))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def authenticate(session, username: str, password: str, *, now: datetime | None = None,
                 max_attempts: int = 5, lock_minutes: int = 15) -> tuple[User | None, str]:
    """Authenticate and persist throttling state. Returns (user, public error)."""
    now = now or datetime.now(timezone.utc)
    user = session.scalar(select(User).where(User.username == username.strip()))
    if user is None or not user.active:
        return None, "Invalid username or password"
    locked_until = user.locked_until
    if locked_until is not None:
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            return None, f"Account locked until {locked_until.astimezone().strftime('%H:%M')}"
        user.locked_until = None
        user.failed_login_attempts = 0
    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= max_attempts:
            user.locked_until = now + timedelta(minutes=lock_minutes)
            user.failed_login_attempts = 0
            message = f"Too many attempts; account locked for {lock_minutes} minutes"
        else:
            message = "Invalid username or password"
        session.add(ActivityLog(user_id=user.id, action="failed login", module="security",
                                details=message))
        session.commit()
        return None, message
    user.failed_login_attempts = 0
    user.locked_until = None
    session.add(ActivityLog(user_id=user.id, action="login", module="security"))
    session.commit()
    return user, ""


def change_password(session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        raise ValueError("Current password is incorrect")
    if len(new_password) < 5 or not any(c.isupper() for c in new_password) or not any(c.islower() for c in new_password) or not any(c.isdigit() for c in new_password):
        raise ValueError("Use at least 5 characters with upper-case, lower-case, and a number")
    if new_password == current_password:
        raise ValueError("New password must be different")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    session.add(ActivityLog(user_id=user.id, action="changed password", module="security"))
    session.commit()


def has_permission(session, user, permission_key: str) -> bool:
    from sqlalchemy import select
    from .models import RolePermission, Permission
    result = session.scalar(
        select(RolePermission.role_id)
        .join(Permission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == user.role_id, Permission.key == permission_key)
        .limit(1)
    )
    return result is not None


class PermissionDenied(PermissionError):
    pass


def require_permission(session, user, permission_key: str) -> None:
    if not has_permission(session, user, permission_key):
        raise PermissionDenied(f"Permission required: {permission_key}")


def permission_keys(session, user) -> set[str]:
    from .models import RolePermission, Permission
    return set(session.scalars(
        select(Permission.key)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == user.role_id)
    ))
