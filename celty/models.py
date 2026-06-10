import importlib.metadata
import os
import platform
import sys
import time
import typing as t
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import PathDistribution
from pathlib import Path

import durationpy
import httpx2 as httpx
import platformdirs
import yaml
from loguru import logger
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    TypeAdapter,
    ValidationError,
    computed_field,
    field_serializer,
    field_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError
from rich.console import Console
from rich.progress import Progress

from celty.constants import METADATA_DIR

Duration = t.Annotated[
    int, BeforeValidator(lambda v: durationpy.from_str(v).total_seconds())
]


class Config(BaseModel):
    apps: list[App]

    @field_validator("apps", mode="after")
    def validate_apps(cls, v) -> list[App]:
        errors = []

        for attr in ["name", "github_url"]:
            counter = Counter(getattr(app, attr) for app in v)

            for value, count in counter.items():
                if count > 1:
                    errors.append(
                        InitErrorDetails(
                            type=PydanticCustomError(
                                "value_error",
                                f'"{attr}" value "{value}" must be unique across all apps '
                                f"({count} occurrences found)",
                            ),
                            loc=("apps",),
                            input=v,
                        )
                    )

        default_counter = Counter(app.default for app in v)
        count = default_counter.most_common(1)[0][1]

        if count > 1:
            errors.append(
                InitErrorDetails(
                    type=PydanticCustomError(
                        "value_error",
                        f"Only one app can be marked as default ({count} default app{'s' if count > 1 else ''} found)",
                    ),
                    loc=("apps",),
                    input=v,
                )
            )

        if errors:
            raise ValidationError.from_exception_data(
                title=cls.__name__, line_errors=errors
            )

        return v

    @classmethod
    def get_default_path(cls) -> Path:
        return platformdirs.user_config_path("celty") / "config.yml"

    @classmethod
    def load(cls, path: Path = None) -> t.Self | None:
        config_path = path or cls.get_default_path()

        logger.debug(f"Attempting to load configuration from {config_path}")

        if config_path.is_file():
            return cls.model_validate(yaml.safe_load(config_path.open()))
        else:
            logger.debug(f"Could not load configuration from {config_path}")

    def get_app(self, app_name: str = None, *, repo_owner: str = None) -> App | None:
        if repo_owner:
            logger.debug(
                f"Looking for app where [bold]repo_owner[/] == [bold]{repo_owner}"
            )

            if app := next((a for a in self.apps if a.repo_owner == repo_owner), None):
                logger.debug(f"Using app {app.name}")
                return app

        if not app_name:
            return self.get_default_app()

        logger.debug(f'Looking for app named "{app_name}"')

        return next((a for a in self.apps if a.name == app_name), None)

    def get_default_app(self) -> App:
        logger.debug(f"Determining default app")

        app = next((a for a in self.apps if a.default), self.apps[0])

        logger.debug(f"Using app: {app}")

        return app


class App(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    client_id: str
    default: bool = False
    repo_owner: str = None
    github_url: httpx.URL = httpx.URL("https://github.com")

    @field_validator("github_url", mode="before")
    def validate_github_url(cls, v) -> httpx.URL:
        try:
            url = httpx.URL(v)
        except TypeError as e:
            raise ValueError(e.args[0]) from None

        errors = []

        if url.scheme not in ["http", "https"]:
            errors.append(
                InitErrorDetails(
                    type=PydanticCustomError(
                        "value_error",
                        "URL must begin with http:// or https://",
                    ),
                    loc="github_url",
                    input=v,
                )
            )

        if not url.host:
            errors.append(
                InitErrorDetails(
                    type=PydanticCustomError("value_error", "URL must have a host"),
                    loc="github_url",
                    input=v,
                )
            )

        if errors:
            raise ValidationError.from_exception_data(
                title=cls.__name__, line_errors=errors
            )

        return url.copy_with(host=url.host.removeprefix("www."))

    @property
    def is_ghes_app(self) -> bool:
        return self.github_url.host != "github.com"

    @property
    def api_url(self) -> httpx.URL:
        if self.is_ghes_app:
            return self.github_url.copy_with(
                path=self.github_url.path.rstrip("/") + "/api/v3"
            )

        return httpx.URL("https://api.github.com")

    @property
    def credential_helper_urls(self) -> list[httpx.URL]:
        return [
            self.github_url,
            self.github_url.copy_with(host=f"*.{self.github_url.host}"),
        ]


class Response(BaseModel):
    @classmethod
    def from_response(cls, response: httpx.Response):
        logger.debug(f"Sent request to {response.request.url}")
        return cls.model_validate(response.raise_for_status().json())


class CodeInfo(Response):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class TokenInfo(Response):
    access_token: str = None
    expires_in: int = None
    error: str = None
    interval: int = None


class StoredToken(BaseModel):
    token: str
    expires_at: float

    @classmethod
    def from_token_info(cls, token_info: TokenInfo) -> t.Self:
        return cls(
            token=token_info.access_token,
            expires_at=time.time() + (token_info.expires_in - 300),
        )


class CeltyDistribution(BaseModel):
    model_config = ConfigDict(alias_generator=lambda s: s.replace("_", "-"))

    @property
    def _distribution(self) -> PathDistribution:
        return importlib.metadata.distribution("celty")

    @property
    def is_binary_build(self) -> bool:
        try:
            pyapp = TypeAdapter(bool).validate_python(os.getenv("PYAPP"))
        except ValueError:
            return False

        return pyapp and sys.argv[0] == "-c"

    @computed_field
    def release(self) -> str:
        return self._distribution.version

    @computed_field
    def build_type(self) -> t.Literal["binary", "python"]:
        return "binary" if self.is_binary_build else "python"

    @computed_field
    def installer(self) -> str | None:
        if not self.is_binary_build:
            return self._distribution.read_text("INSTALLER")

    @computed_field
    def python(self) -> str | None:
        return f"{platform.python_implementation()} {platform.python_version()}"

    @computed_field
    def platform(self) -> str:
        return " ".join(platform.platform(terse=True).split("-"))

    @computed_field
    def architecture(self) -> str:
        return platform.machine()
    
    def info(self) -> str:
        return f"Celty {self.release}"
    
    def long_info(self) -> str:
        lines = [self.info()]

        for key, value in self.model_dump(exclude_none=True, by_alias=True).items():
            lines.append(f"{key}: {value}")

        return "\n".join(lines)
