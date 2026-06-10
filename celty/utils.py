import subprocess
import sys
import time
import typing as t
from pathlib import Path

import httpx2 as httpx
import rich
import typer
from loguru import logger
from pydantic import TypeAdapter, validate_call
from rich.console import Console
from rich.panel import Panel

from celty.models import App, Duration, StoredToken, TokenInfo

KEYRING_NAME = "com.celsiusnarhwal.celty"


def fail(message: str, title: str = "Error") -> None:
    panel = Panel(message, title=title, title_align="left", border_style="red")
    rich.print(panel, file=sys.stderr)

    raise typer.Exit(1)


def run_keyring_command(
    *command: str, keyring_path: Path | None, **kwargs
) -> str | None:
    if keyring_path:
        cmd = [str(keyring_path), *command]

        logger.debug(f"Running [bold]{str(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)

        try:
            result.check_returncode()
        except subprocess.CalledProcessError, FileNotFoundError:
            logger.debug(
                f"Command [bold]{cmd} failed with return code {result.returncode}. stderr: {result.stderr.strip()}"
            )
        else:
            return result.stdout.strip()


@validate_call()
def save_token(app: App, token_info: TokenInfo, *, keyring_path: Path | None) -> None:
    run_keyring_command(
        "set",
        KEYRING_NAME,
        app.client_id,
        input=StoredToken.from_token_info(token_info).model_dump_json(),
        keyring_path=keyring_path,
    )


@validate_call()
def load_token(
    app: App, *, keyring_path: Path | None = None, minimum_validity: int | None = None
) -> str | None:
    stored_token_json = run_keyring_command(
        "get", KEYRING_NAME, app.client_id, keyring_path=keyring_path
    )

    if not stored_token_json:
        return None

    try:
        stored_token = StoredToken.model_validate_json(stored_token_json)
    except ValueError:
        return None

    if minimum_validity and (stored_token.expires_at - time.time()) < minimum_validity:
        return None

    if (
        httpx.get(
            app.api_url,
            headers={"Authorization": f"Bearer {stored_token.token}"},
        ).status_code
        == 200
    ):
        return stored_token.token


def log_sink(message) -> None:
    highlight = message.record["extra"].get("highlight", True)
    console = Console(stderr=True, highlight=highlight)
    console.print(f"[grey50]- {message.strip()}")


def set_verbosity(verbose: bool):
    logger.remove()
    logger.add(level="DEBUG" if verbose else "INFO", sink=log_sink, format="{message}")


# Stupid workaround to force Typer to display the type of --minimum-validity as "Duration".


def _duration_parser_wrapper(func: t.Callable) -> t.Callable:
    def duration(*args, **kwargs):
        return func(*args, **kwargs)

    return duration


duration_parser = _duration_parser_wrapper(TypeAdapter(Duration).validate_python)
