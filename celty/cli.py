import contextlib
import os
import shutil
import sys
import time
import typing as t
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

import httpx2 as httpx
import typer
from dulwich.config import ConfigFile
from dulwich.errors import NotGitRepository
from dulwich.repo import Repo
from loguru import logger
from merge_args import merge_args
from platformdirs import user_config_path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from celty import utils
from celty.constants import CELTY_ROOT
from celty.models import (
    App,
    CeltyDistribution,
    CodeInfo,
    Config,
    TokenInfo,
)

cli = typer.Typer(no_args_is_help=True, add_completion=False)

VerboseOption = t.Annotated[
    bool,
    typer.Option(
        "--verbose",
        "-v",
        envvar="CELTY_VERBOSE",
        help="Show verbose output.",
        rich_help_panel="Global Options",
    ),
]


@cli.command("init")
def init(
    ctx: typer.Context,
    config_file: t.Annotated[
        Path,
        typer.Option(
            "--config-file",
            "-C",
            envvar="CELTY_CONFIG_FILE",
            file_okay=True,
            dir_okay=False,
            help="The path at which to initialize a configuration file.",
        ),
    ] = None,
    force: t.Annotated[
        bool,
        typer.Option(
            "--force", "-f", help="Override an existing configuration file if present."
        ),
    ] = False,
    verbose: VerboseOption = False,
):
    """
    Initialize a configuration file.
    """
    utils.set_verbosity(verbose)
    logger.debug(f"Received arguments: {ctx.params}")

    config_path = config_file or Config.get_default_path()

    if config_path.exists() and not force:
        utils.fail(
            f"{config_path} already exists. Use [bold cyan]--force[/] / [bold green]-f[/] to overwrite."
        )

    example_config = CELTY_ROOT / "templates" / "config.yml"

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(example_config.read_text())

    print(f"Configuration file initialized at {config_path}")


@cli.command("get")
@cli.command("credential", hidden=True, context_settings={"allow_extra_args": True})
def get(
    ctx: typer.Context,
    app: t.Annotated[
        str,
        typer.Option(
            "--app",
            "-a",
            envvar="CELTY_APP",
            help="The app to authenticate with. No effect if --client-id is passed.",
        ),
    ] = None,
    client_id: t.Annotated[
        str,
        typer.Option(
            "--client-id",
            "-c",
            envvar="CELTY_CLIENT_ID",
            help="The client ID of the app to authenticate with.",
            rich_help_panel="Single-Use Authentication Options",
        ),
    ] = None,
    github_url: t.Annotated[
        str,
        typer.Option(
            "--github-url",
            "-u",
            envvar="CELTY_GITHUB_URL",
            help="The GitHub host to authenticate with.",
            rich_help_panel="Single-Use Authentication Options",
        ),
    ] = "https://github.com",
    minimum_validity: t.Annotated[
        int,
        typer.Option(
            "--minimum-validity",
            "-m",
            envvar="CELTY_MINIMUM_VALIDITY",
            parser=utils.duration_parser,
            help="The minimum amount of time for which a token retrieved from the credential store must be valid. "
            "Effectively caps at 8 hours.",
        ),
    ] = "1h",
    no_store: t.Annotated[
        bool,
        typer.Option(
            "--no-store",
            "-n",
            envvar="CELTY_NO_STORE",
            help="Do not store the token in, or retrieve it from, the credential store.",
        ),
    ] = False,
    no_web: t.Annotated[
        bool,
        typer.Option(
            "--no-web",
            "-W",
            envvar="CELTY_NO_WEB",
            help="Do not attempt to open the login page in a browser.",
        ),
    ] = False,
    keyring_path: t.Annotated[
        Path,
        typer.Option(
            "--keyring-path",
            "-k",
            envvar="CELTY_KEYRING_PATH",
            help="The path to a Keyring binary.",
        ),
    ] = shutil.which("keyring"),
    config_file: t.Annotated[
        Path,
        typer.Option(
            "--config-file",
            "-C",
            envvar="CELTY_CONFIG_FILE",
            file_okay=True,
            dir_okay=False,
            help="The path to a configuration file. No effect if --client-id is passed.",
        ),
    ] = None,
    verbose: VerboseOption = False,
):
    """
    Get a GitHub access token and print it to standard output.
    """
    utils.set_verbosity(verbose)
    logger.debug(f"Received arguments: {ctx.params}")

    credential_helper = ctx.command.name == "credential"

    celty_app = None
    repo_owner = None
    token = None

    if credential_helper:
        logger.debug("Invoked as credential helper")

        if ctx.args[-1] != "get":
            raise typer.Exit(0 if ctx.args[-1] in ["store", "erase"] else 1)

        credential_input = {
            k: v for k, v in [line.split("=", 1) for line in sys.stdin.readlines()]
        }

        logger.debug(f"Caller input: {credential_input}")

        if repo_path := credential_input.get("path"):
            repo_owner = repo_path.split("/")[0]
            logger.debug(f"Repo owner: {repo_owner}")

    if client_id:
        logger.debug("Client ID provided, will not read config file")
        celty_app = App(
            name=uuid.uuid4().hex, client_id=client_id, github_url=github_url
        )
    elif config := Config.load(config_file):
        celty_app = config.get_app(app, repo_owner=repo_owner)

        if not celty_app:
            utils.fail(f'No app named "{app} is configured.')
    else:
        utils.fail(
            "No client ID was provided. Either pass [bold cyan]--client-id[/] / [bold green]-c[/] or create a "
            "configuration file."
        )

    if not no_store:
        token = utils.load_token(
            celty_app, keyring_path=keyring_path, minimum_validity=minimum_validity
        )

    if not token:
        logger.debug("No saved token found; beginning authorization process")

        gh = httpx.Client(
            base_url=celty_app.github_url, headers={"Accept": "application/json"}
        )

        code_info = CodeInfo.from_response(
            gh.post(
                "/login/device/code",
                params={
                    "client_id": celty_app.client_id,
                },
            )
        )

        polling_interval = code_info.interval
        logger.debug(f"Will poll every {polling_interval} seconds")

        if os.getenv("CELTY_VHS_RECORDING"):
            import pyperclip

            pyperclip.copy(code_info.user_code)

        if not no_web:
            logger.debug(
                f"Attempting to open {code_info.verification_uri} in a web browser"
            )
            webbrowser.open(code_info.verification_uri)

        console = Console(stderr=True)
        prompt = f"Go to {code_info.verification_uri} and enter the code {code_info.user_code}."

        plain_prompt = verbose or console.width < len(prompt) + 10
        context_manager = contextlib.nullcontext if plain_prompt else console.status

        with context_manager(prompt) as progress:
            if plain_prompt:
                console.print(
                    f"Go to {code_info.verification_uri} and enter the code {code_info.user_code}.",
                )

            logger.debug("Prompting user to authorize")

            while True:
                token_info = TokenInfo.from_response(
                    gh.post(
                        "/login/oauth/access_token",
                        params={
                            "client_id": celty_app.client_id,
                            "device_code": code_info.device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )
                )

                if not token_info.error:
                    logger.debug("Authorization succeded")
                    break

                errors = {
                    "expired_token": "You took too long to enter the code. Please try again.",
                    "incorrect_client_credentials": "The client ID is incorrect. Please double check the client ID and "
                    "try again.",
                    "access_denied": "You denied access.",
                    "device_flow_disabled": "Device flow is not enabled for the application.",
                }

                if error_message := errors.get(token_info.error):
                    if not plain_prompt:
                        progress.stop()

                    utils.fail(error_message)

                if token_info.interval:
                    polling_interval = token_info.interval
                    logger.debug(
                        f"GitHub said to slow down; will now poll every {polling_interval} seconds"
                    )

                logger.debug(
                    f"Authorization pending; checking again in {polling_interval} seconds"
                )
                time.sleep(polling_interval)

            if not plain_prompt:
                progress.stop()

            if not no_store:
                utils.save_token(
                    celty_app, token_info=token_info, keyring_path=keyring_path
                )

        token = token_info.access_token

    if credential_helper:
        logger.debug("Printing credential helper authentication string")
        sys.stdout.write(f"username=git\npassword={token}")
    else:
        logger.debug("Printing token")
        print(token)


# noinspection PyUnusedLocal
# `--verbose` is not included here because it's inherited from `get()` via `merge_args`.
@cli.command("helper")
@merge_args(get)
def helper(
    ctx: typer.Context,
    global_: t.Annotated[
        bool,
        typer.Option("--global", "-g", help="Modify the global Git configuration."),
    ] = False,
    **kwargs,
):
    """
    Configure Celty as a Git credential helper. All options other than --global and --verbose will be passed
    to [bold cyan]celty get[/] when it is invoked by Git.
    """
    utils.set_verbosity(kwargs["verbose"])
    logger.debug(f"Received arguments: {ctx.params}")

    args = [
        arg
        for arg in sys.argv[1:]
        if arg not in [ctx.command.name, "--global", "-g", "--verbose", "-v"]
    ]

    helper_cmd = "!celty credential " + " ".join(args)

    logger.debug(f"Git will run: {helper_cmd.lstrip('!')}")

    if not global_:
        try:
            logger.debug(f"Looking for Git repository in {Path.cwd()} or its parents")
            repo = Repo.discover()
        except NotGitRepository:
            utils.fail(
                "The current working directory is not a Git repository. If you meant to configure Celty as a "
                "Git credential helper globally, use [bold cyan]--global[/] / [bold green]-g[/]."
            )
        else:
            logger.debug(f"Loaded Git configuration from repository at {repo.path}")
            git_config = repo.get_config()
    else:
        git_config_path = None
        potential_paths = [
            Path(os.getenv("GIT_CONFIG_GLOBAL", "")),
            user_config_path("git") / "config",
            Path("~/.gitconfig").expanduser(),
        ]

        for path in potential_paths:
            path = path.resolve()
            logger.debug(f"Looking for global Git configuration file at {path}")

            if path.is_file():
                git_config_path = path
                logger.debug(f"Found global Git configuration file at {path}")
                break

        if git_config_path:
            git_config = ConfigFile.from_path(git_config_path)
            logger.debug(f"Loaded Git configuration from {git_config.path}")

        else:
            utils.fail(
                "No global Git configuration exists. Please initialize one, then try again."
            )

    celty_app = None

    if config := Config.load(kwargs["config_file"]):
        celty_app = config.get_app(kwargs["app"])

    if not celty_app:
        celty_app = App(name=uuid.uuid4().hex, client_id=uuid.uuid4().hex)

    for url in celty_app.credential_helper_urls:
        logger.debug(f"Configuring credential helper for {url}")
        section = (b"credential", str(url).encode())

        # noinspection PyUnboundLocalVariable
        try:
            del git_config[section]
        except KeyError:
            pass

        git_config.add(section, "helper", "")
        git_config.add(section, "helper", helper_cmd)
        git_config.add(section, "useHttpPath", True)

    logger.debug(f"Writing Git configuration to {git_config.path}")
    git_config.write_to_path(git_config.path)


if CeltyDistribution().is_binary_build:

    @cli.command(
        "self",
        add_help_option=False,
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
        hidden=True,
    )
    def self():
        raise typer.Exit(1)


@cli.callback(
    invoke_without_command=True,
    epilog=f"Copyright (c) {datetime.now().astimezone().year} celsius narhwal. Thank you kindly for your attention.",
)
def main(
    ctx: typer.Context,
    version: t.Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            is_eager=True,
            help="Show Celty's version.",
        ),
    ] = False,
    verbose: VerboseOption = False,
):
    """
    Celty generates short-lived GitHub access tokens from the command line. https://github.com/celsiusnarhwal/celty
    """
    utils.set_verbosity(verbose)

    if version:
        distribution = CeltyDistribution()
        print(distribution.long_info() if verbose else distribution.info())


def entrypoint():
    cli(prog_name="celty")


if __name__ == "__main__":
    entrypoint()
