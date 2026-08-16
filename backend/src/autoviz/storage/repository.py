"""Data-access helpers over the ORM models (``autoviz.models``).

Thin CRUD returning ORM objects or plain values; the API routes shape them into
responses. ``resolve_dataset`` is the ownership + lazy-reload gate every dataset
route goes through.
"""

import datetime
import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from autoviz.errors import UNKNOWN_DATASET, make_error
from autoviz.models import (
    ChatMessage,
    Conversation,
    Dashboard,
    DashboardWidget,
    McpKey,
    OAuthAccount,
    PasswordResetToken,
    SavedChart,
    User,
    UserDataset,
    UserSession,
)
from autoviz.services.registry import DatasetRegistry

FORBIDDEN = "FORBIDDEN"  # API-level code (not a service taxonomy code); maps to 403


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# --- users & tokens ----------------------------------------------------------


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email.strip().lower()))


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username))


def get_oauth_account(
    session: Session, provider: str, provider_user_id: str
) -> OAuthAccount | None:
    return session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )


def get_user_by_oauth(
    session: Session, provider: str, provider_user_id: str
) -> User | None:
    account = get_oauth_account(session, provider, provider_user_id)
    if account is None:
        return None
    return session.get(User, account.user_id)


def list_oauth_providers(session: Session, user_id: str) -> list[str]:
    rows = session.scalars(
        select(OAuthAccount.provider).where(OAuthAccount.user_id == user_id)
    ).all()
    return list(rows)


def link_oauth_account(
    session: Session,
    user: User,
    *,
    provider: str,
    provider_user_id: str,
    access_token: str | None = None,
) -> OAuthAccount:
    existing = get_oauth_account(session, provider, provider_user_id)
    if existing is not None:
        if existing.user_id != user.id:
            raise ValueError("oauth_identity_taken")
        if access_token is not None:
            existing.access_token = access_token
            session.commit()
        return existing
    account = OAuthAccount(
        user_id=user.id,
        provider=provider,
        provider_user_id=provider_user_id,
        access_token=access_token,
    )
    session.add(account)
    session.commit()
    return account


def create_user(
    session: Session,
    email: str,
    password_hash: str | None,
    *,
    username: str | None = None,
    email_verified: bool = False,
) -> User:
    user = User(
        email=email.strip().lower(),
        password_hash=password_hash,
        username=username,
        email_verified=email_verified,
    )
    session.add(user)
    session.commit()
    return user


def unique_username(session: Session, base: str) -> str:
    candidate = base[:64]
    if session.scalar(select(User).where(User.username == candidate)) is None:
        return candidate
    for i in range(2, 1000):
        suffix = f"-{i}"
        candidate = base[: 64 - len(suffix)] + suffix
        if session.scalar(select(User).where(User.username == candidate)) is None:
            return candidate
    return f"{base[:40]}-{secrets.token_hex(4)}"


def set_user_password(session: Session, user: User, password_hash: str) -> None:
    user.password_hash = password_hash
    session.commit()


def create_password_reset_token(
    session: Session, user_id: str, ttl_hours: int = 1
) -> PasswordResetToken:
    # Invalidate prior unused tokens for this user.
    prior = session.scalars(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
    ).all()
    for row in prior:
        session.delete(row)
    row = PasswordResetToken(
        user_id=user_id,
        token=secrets.token_urlsafe(32),
        expires_at=_now() + datetime.timedelta(hours=ttl_hours),
    )
    session.add(row)
    session.commit()
    return row


def get_password_reset_token(session: Session, token: str) -> PasswordResetToken | None:
    return session.scalar(select(PasswordResetToken).where(PasswordResetToken.token == token))


def create_token(session: Session, user_id: str, ttl_hours: int = 24 * 7) -> UserSession:
    token = UserSession(
        token=secrets.token_urlsafe(32),
        user_id=user_id,
        expires_at=_now() + datetime.timedelta(hours=ttl_hours),
    )
    session.add(token)
    session.commit()
    return token


def get_user_for_token(session: Session, token: str) -> User | None:
    row = session.scalar(select(UserSession).where(UserSession.token == token))
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:  # SQLite returns naive; treat stored time as UTC
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    if expires <= _now():
        return None
    return session.get(User, row.user_id)


def delete_token(session: Session, token: str) -> None:
    row = session.scalar(select(UserSession).where(UserSession.token == token))
    if row is not None:
        session.delete(row)
        session.commit()


def delete_all_tokens_for_user(session: Session, user_id: str) -> None:
    rows = session.scalars(select(UserSession).where(UserSession.user_id == user_id)).all()
    for row in rows:
        session.delete(row)
    session.commit()


def clear_oauth_access_tokens(session: Session, user_id: str) -> list[tuple[str, str]]:
    """Clear stored provider tokens; return (provider, token) pairs that were set."""
    revoked: list[tuple[str, str]] = []
    accounts = session.scalars(
        select(OAuthAccount).where(OAuthAccount.user_id == user_id)
    ).all()
    for account in accounts:
        if account.access_token:
            revoked.append((account.provider, account.access_token))
            account.access_token = None
    session.commit()
    return revoked


# --- dataset metadata --------------------------------------------------------


def add_dataset_meta(
    session: Session,
    *,
    dataset_id: str,
    user_id: str,
    filename: str,
    file_path: str,
    row_count: int | None = None,
    column_count: int | None = None,
    size_bytes: int | None = None,
) -> UserDataset:
    existing = get_dataset_meta(session, dataset_id)
    if existing is not None:  # idempotent re-upload of the same registry id
        existing.filename = filename
        existing.file_path = file_path
        existing.row_count = row_count
        existing.column_count = column_count
        existing.size_bytes = size_bytes
        session.commit()
        return existing
    meta = UserDataset(
        user_id=user_id,
        dataset_id=dataset_id,
        filename=filename,
        file_path=file_path,
        row_count=row_count,
        column_count=column_count,
        size_bytes=size_bytes,
    )
    session.add(meta)
    session.commit()
    return meta


def get_dataset_meta(session: Session, dataset_id: str) -> UserDataset | None:
    return session.scalar(select(UserDataset).where(UserDataset.dataset_id == dataset_id))


def list_dataset_meta(session: Session, user_id: str) -> list[UserDataset]:
    return list(session.scalars(select(UserDataset).where(UserDataset.user_id == user_id)))


def delete_dataset_meta(session: Session, dataset_id: str) -> None:
    meta = get_dataset_meta(session, dataset_id)
    if meta is not None:
        session.delete(meta)
        session.commit()


def resolve_dataset(session: Session, registry: DatasetRegistry, dataset_id: str, user_id: str):
    """Return (record, error). Enforces ownership; the registry restores the frame.

    Reloading is no longer this function's job: ``DatasetRegistry.get`` calls its
    loader on a miss (``storage.blobs``), so a dataset that was evicted under
    memory pressure or lost to a restart comes back here transparently.
    """
    meta = get_dataset_meta(session, dataset_id)
    if meta is None:
        return None, make_error(UNKNOWN_DATASET, f"Unknown dataset_id: {dataset_id}")
    if meta.user_id != user_id:
        return None, {"error": "You do not own this dataset", "error_code": FORBIDDEN}
    record = registry.get(dataset_id)
    if record is None:
        return None, make_error(
            UNKNOWN_DATASET, f"Stored data for {dataset_id} is no longer available"
        )
    return record, None


# --- saved charts ------------------------------------------------------------


def create_chart(session: Session, user_id: str, **fields) -> SavedChart:
    chart = SavedChart(user_id=user_id, **fields)
    session.add(chart)
    session.commit()
    return chart


def update_chart(session: Session, chart: SavedChart, **fields) -> SavedChart:
    """Overwrite the given columns on a saved chart.

    Only keys actually present are written, so a caller sending just a new spec
    does not blank the name it did not mention.
    """
    for key, value in fields.items():
        setattr(chart, key, value)
    session.commit()
    return chart


def get_chart(session: Session, chart_id: str) -> SavedChart | None:
    return session.get(SavedChart, chart_id)


def list_charts(session: Session, user_id: str) -> list[SavedChart]:
    return list(session.scalars(select(SavedChart).where(SavedChart.user_id == user_id)))


def delete_chart(session: Session, chart: SavedChart) -> None:
    session.delete(chart)
    session.commit()


# --- dashboards --------------------------------------------------------------


def create_dashboard(session: Session, user_id: str, name: str) -> Dashboard:
    dashboard = Dashboard(user_id=user_id, name=name)
    session.add(dashboard)
    session.commit()
    return dashboard


def get_dashboard(session: Session, dashboard_id: str) -> Dashboard | None:
    return session.get(Dashboard, dashboard_id)


def list_dashboards(session: Session, user_id: str) -> list[Dashboard]:
    return list(session.scalars(select(Dashboard).where(Dashboard.user_id == user_id)))


def set_dashboard_widgets(session: Session, dashboard: Dashboard, widgets: list[dict]) -> Dashboard:
    """Replace a dashboard's widgets with the given [{chart_id, x, y, w, h, order}]."""
    dashboard.widgets.clear()
    for i, w in enumerate(widgets):
        dashboard.widgets.append(
            DashboardWidget(
                chart_id=w["chart_id"],
                x=int(w.get("x", 0)),
                y=int(w.get("y", 0)),
                w=int(w.get("w", 6)),
                h=int(w.get("h", 4)),
                order=int(w.get("order", i)),
            )
        )
    session.commit()
    return dashboard


def delete_dashboard(session: Session, dashboard: Dashboard) -> None:
    session.delete(dashboard)
    session.commit()


# --- conversations -----------------------------------------------------------


def get_conversation(session: Session, user_id: str, dashboard_id: str) -> Conversation | None:
    return session.scalar(
        select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.dashboard_id == dashboard_id,
        )
    )


def set_conversation(
    session: Session,
    user_id: str,
    dashboard_id: str,
    *,
    messages: list[dict],
    thread_id: str | None = None,
    set_thread_id: bool = True,
) -> Conversation:
    """Upsert a board's transcript, replacing every message it had.

    Replace rather than append because the client holds the whole transcript in
    state and is the only writer: an append endpoint would have to reason about
    which messages the server already saw, and would drift the moment a save was
    retried after a timeout that had in fact succeeded.

    ``set_thread_id=False`` leaves a stored thread alone, for the caller that is
    only writing messages and does not know what the agent thread currently is.
    """
    conversation = get_conversation(session, user_id, dashboard_id)
    if conversation is None:
        conversation = Conversation(user_id=user_id, dashboard_id=dashboard_id)
        session.add(conversation)
    if set_thread_id:
        conversation.thread_id = thread_id

    conversation.messages.clear()
    for i, m in enumerate(messages):
        conversation.messages.append(
            ChatMessage(
                seq=i,
                client_id=m.get("client_id"),
                role=m["role"],
                content=m.get("content") or "",
                chart_id=m.get("chart_id"),
                referenced_title=m.get("referenced_title"),
                options=m.get("options"),
                timestamp_ms=m.get("timestamp_ms"),
            )
        )
    # Touch it even on a messages-only change: onupdate does not fire for a
    # parent whose own columns did not change, and "when did this board last get
    # talked to" is the one thing the column is for.
    conversation.updated_at = _now()
    session.commit()
    return conversation


def delete_conversation(session: Session, conversation: Conversation) -> None:
    session.delete(conversation)
    session.commit()


# --- MCP connection keys -----------------------------------------------------
#
# The plaintext key exists only in the response that creates it. Everything
# stored and everything looked up is the SHA-256, so a dump of this table yields
# no working links (`Docs/26 §4.1`).


def hash_mcp_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def create_mcp_key(
    session: Session,
    user_id: str,
    *,
    label: str = "",
    profile: str = "host",
    expires_at: datetime.datetime | None = None,
) -> tuple[McpKey, str]:
    """Mint a key. Returns (row, plaintext) — the plaintext is never stored.

    32 bytes of CSPRNG in base64url: not guessable, and URL-safe because it goes
    in a path segment.
    """
    plaintext = secrets.token_urlsafe(32)
    row = McpKey(
        user_id=user_id,
        token_hash=hash_mcp_key(plaintext),
        label=label,
        profile=profile,
        expires_at=expires_at,
    )
    session.add(row)
    session.commit()
    return row, plaintext


def get_usable_mcp_key(session: Session, key: str) -> McpKey | None:
    """The row for `key`, or None if unknown, revoked or expired.

    One lookup by indexed hash — no scan, so the work does not depend on how
    many keys exist and cannot be timed to learn anything about them.
    """
    row = session.scalar(select(McpKey).where(McpKey.token_hash == hash_mcp_key(key)))
    if row is None or not row.is_usable():
        return None
    return row


def list_mcp_keys(session: Session, user_id: str) -> list[McpKey]:
    """Every key the user has minted, revoked ones included — a revoked key that
    vanishes from the list gives no way to confirm the revocation happened."""
    return list(
        session.scalars(
            select(McpKey).where(McpKey.user_id == user_id).order_by(McpKey.created_at)
        )
    )


def revoke_mcp_key(session: Session, user_id: str, key_id: str) -> bool:
    """Revoke by id, scoped to the owner. Idempotent."""
    row = session.scalar(
        select(McpKey).where(McpKey.id == key_id, McpKey.user_id == user_id)
    )
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = _now()
        session.commit()
    return True


# How stale `last_used_at` may get. A write per tool call would turn a read-only
# analysis into a stream of UPDATEs; a minute is precise enough for "is this old
# link still live?", which is the only question the column answers.
MCP_KEY_TOUCH_INTERVAL = datetime.timedelta(minutes=1)


def touch_mcp_key(session: Session, row: McpKey) -> None:
    now = _now()
    last = row.last_used_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=datetime.timezone.utc)
    if last is not None and now - last < MCP_KEY_TOUCH_INTERVAL:
        return
    row.last_used_at = now
    session.commit()
