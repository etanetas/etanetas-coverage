import asyncio
import bcrypt
import secrets
import sys
from datetime import datetime

import typer
from rich import print as rprint
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.admin import ApiKey, User

from importlib.metadata import version as pkg_version

app = typer.Typer()


@app.command("create-admin")
def create_admin(
    username: str = typer.Option(...),
    email: str = typer.Option(...),
):
    try:
        asyncio.run(_create_admin(username, email))
    except Exception as e:
        rprint(f"[red]ERROR: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1)


@app.command("create-key")
def create_key(
    username: str = typer.Option(..., help="Username of an existing user"),
    name: str = typer.Option("default", help="Label for the new key"),
):
    """Generate a new API key for an existing user."""
    try:
        asyncio.run(_create_key(username, name))
    except Exception as e:
        rprint(f"[red]ERROR: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1)


@app.command("revoke-key")
def revoke_key(
    username: str = typer.Option(..., help="Revoke all active keys for this user"),
):
    """Revoke all active API keys for a user."""
    try:
        asyncio.run(_revoke_key(username))
    except Exception as e:
        rprint(f"[red]ERROR: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1)


@app.command("list-users")
def list_users():
    """List all users and their active key count."""
    try:
        asyncio.run(_list_users())
    except Exception as e:
        rprint(f"[red]ERROR: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1)


@app.command("version")
def show_version():
    rprint(f"\netanetas-cli {pkg_version('etanetas-coverage')}\n")


async def _create_admin(username: str, email: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        existing = result.scalar_one_or_none()

        if existing is not None:
            rprint(f"[red]User '{username}' already exists.[/red]", file=sys.stderr)
            raise typer.Exit(code=1)

        user = User(username=username, email=email, role="admin", active=True)
        session.add(user)
        await session.flush()

        raw_key, api_key = _new_api_key(user.id, "initial")
        session.add(api_key)
        await session.commit()

        rprint(f"\n[green]Admin created: {username} <{email}>[/green]")
        rprint(f"[yellow]API key (shown ONCE): {raw_key}[/yellow]\n")


async def _create_key(username: str, name: str) -> None:
    async with AsyncSessionLocal() as session:
        user = await _require_user(session, username)

        raw_key, api_key = _new_api_key(user.id, name)
        session.add(api_key)
        await session.commit()

        rprint(f"\n[green]New key for {username} (name: {name})[/green]")
        rprint(f"[yellow]API key (shown ONCE): {raw_key}[/yellow]\n")


async def _revoke_key(username: str) -> None:
    async with AsyncSessionLocal() as session:
        user = await _require_user(session, username)

        result = await session.execute(
            select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
        )
        keys = result.scalars().all()

        if not keys:
            rprint(f"[yellow]No active keys found for '{username}'.[/yellow]")
            return

        now = datetime.now()
        for key in keys:
            key.revoked_at = now

        await session.commit()
        rprint(f"[green]Revoked {len(keys)} key(s) for '{username}'.[/green]")


async def _list_users() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).order_by(User.created_at))
        users = result.scalars().all()

        if not users:
            rprint("[yellow]No users found.[/yellow]")
            return

        for user in users:
            keys_result = await session.execute(
                select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
            )
            active_keys = len(keys_result.scalars().all())
            status = "[green]active[/green]" if user.active else "[red]inactive[/red]"
            rprint(f"  {user.username}  <{user.email}>  role={user.role}  keys={active_keys}  {status}")


async def _require_user(session, username: str) -> User:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        rprint(f"[red]User '{username}' not found.[/red]", file=sys.stderr)
        raise typer.Exit(code=1)
    return user


def _new_api_key(user_id, name: str) -> tuple[str, ApiKey]:
    raw_key = "etn_pk_" + secrets.token_urlsafe(32)
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()
    return raw_key, ApiKey(user_id=user_id, key_hash=key_hash, name=name)


if __name__ == "__main__":
    app()