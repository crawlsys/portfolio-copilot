"""Tracker admin CLI. Entrypoint: `python -m apps.cli`."""

from __future__ import annotations

import click


@click.group()
def main() -> None:
    """Tracker administration commands."""


@main.command("seed-fake-account")
def seed_fake_account() -> None:
    """Seed a fake account for local development. (Implemented in chunk 6.)"""
    click.echo("seed-fake-account: not yet implemented (see chunk 6)")


if __name__ == "__main__":
    main()
