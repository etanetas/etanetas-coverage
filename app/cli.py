import asyncio
import bcrypt
import secrets
import sys

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

        raw_key = "etn_pk_" + secrets.token_urlsafe(32)
        key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()

        api_key = ApiKey(user_id=user.id, key_hash=key_hash, name="initial")
        session.add(api_key)

        await session.commit()

        rprint(f"\n[green]Admin created: {username} <{email}>[/green]")
        rprint(f"[yellow]API key (shown ONCE): {raw_key}[/yellow]\n")

if __name__ == "__main__":
    app()