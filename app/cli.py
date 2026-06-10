import asyncio
import secrets
import sys
from importlib.metadata import version as pkg_version
from pathlib import Path

import bcrypt
import typer
from rich import print as rprint
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.gis_import import GisImportError, ImportOptions, ImportReport, run_import
from app.logging_config import configure_logging
from app.models.admin import ApiKey, User
from app.time import now

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
        raise typer.Exit(code=1) from None


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
        raise typer.Exit(code=1) from None


@app.command("revoke-key")
def revoke_key(
    username: str = typer.Option(..., help="Revoke all active keys for this user"),
):
    """Revoke all active API keys for a user."""
    try:
        asyncio.run(_revoke_key(username))
    except Exception as e:
        rprint(f"[red]ERROR: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1) from None


@app.command("list-users")
def list_users():
    """List all users and their active key count."""
    try:
        asyncio.run(_list_users())
    except Exception as e:
        rprint(f"[red]ERROR: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1) from None


@app.command("version")
def show_version():
    rprint(f"\netanetas-cli {pkg_version('etanetas-coverage')}\n")


@app.command("import-gis")
def import_gis(
    shapefile: list[Path] = typer.Option(
        ..., "--shapefile", help="Path to a .shp file (repeatable, lines and/or points)"
    ),
    technology: str = typer.Option(..., help="Technology variant_code, e.g. gpon"),
    distance: float = typer.Option(..., help="Max distance in meters from the network"),
    username: str = typer.Option(..., help="Existing user recorded as created_by"),
    status: str = typer.Option("available", help="Offering status"),
    download: int | None = typer.Option(None, help="Override max_download_mbps"),
    upload: int | None = typer.Option(None, help="Override max_upload_mbps"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run everything, roll back at the end"),
):
    """Import network coverage from GIS shapefiles as address offerings."""
    configure_logging()
    options = ImportOptions(
        shapefiles=shapefile,
        technology=technology,
        distance=distance,
        username=username,
        status=status,
        download=download,
        upload=upload,
        dry_run=dry_run,
    )
    try:
        asyncio.run(_import_gis(options))
    except GisImportError as e:
        rprint(f"[red]ERROR: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1) from None
    except Exception as e:
        rprint(f"[red]ERROR: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1) from None


async def _import_gis(options: ImportOptions) -> None:
    console = Console()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Starting…", total=None)
        report = await run_import(
            options, progress=lambda stage: progress.update(task, description=stage)
        )
    _print_report(console, report, options)


def _print_report(console: Console, report: ImportReport, options: ImportOptions) -> None:
    title = "GIS import — dry run (nothing saved)" if options.dry_run else "GIS import"
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("Geometries loaded", str(report.geometries_loaded))
    table.add_row("Inactive records skipped", str(report.inactive_skipped))
    table.add_row("Addresses matched", str(report.addresses_matched))
    table.add_row("Offerings created", f"[green]{report.offerings_created}[/green]")
    table.add_row("Existing skipped", str(report.existing_skipped))
    console.print(table)


async def _create_admin(username: str, email: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        existing = result.scalar_one_or_none()

        if existing is not None:
            rprint(f"[red]User '{username}' already exists.[/red]", file=sys.stderr)
            raise typer.Exit(code=1) from None

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

        current = now()
        for key in keys:
            key.revoked_at = current

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
        raise typer.Exit(code=1) from None
    return user


def _new_api_key(user_id, name: str) -> tuple[str, ApiKey]:
    raw_key = "etn_pk_" + secrets.token_urlsafe(32)
    key_prefix = raw_key[:11]
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()
    return raw_key, ApiKey(user_id=user_id, key_hash=key_hash, key_prefix=key_prefix, name=name)


if __name__ == "__main__":
    app()