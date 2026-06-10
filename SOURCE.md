# Building Celty

> [!warning]
> Building Celty from source is not supported. Please don't open issues if things break.

> [!important]
> If you're on Windows, note that the instructions in this document assume a POSIX shell.

[Install uv](https://docs.astral.sh/uv/getting-started/installation), clone this repository, and `cd` into wherever you cloned it. Then:

## Binary builds

[Install Rust](https://rust-lang.org/tools/install/), then run:

```shell
uv run poe build-binary
```

This invokes a [Poe](http://poethepoet.natn.io/index.html) task that is equivalent to running the following commands:

```shell
export PYAPP_UV_ENABLED=true
export RUSTFLAGS="-C target-feature=+crt-static"
export SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0+$(uuidgen)
rm -rf dist
uv build --wheel
export PYAPP_PROJECT_PATH=$(realpath dist/*.whl)
uvx hatch build -t binary
mv dist/binary/celty-* dist/binary/celty
```

Celty's binaries are built with [PyApp](https://ofek.dev/pyapp). PyApp provides a number of options to customize builds, which you can read about in [its documentation](https://ofek.dev/pyapp/latest/config/project/).

To build binaries for platforms other than your own, see [Rust's documentation on cross-compilation](https://rust-lang.github.io/rustup/cross-compilation.html).

## Python builds

Simply run:

```shell
uv build
```

This will generate a wheel and source distribution in the `dist` directory. You can choose to only
make one or the other by appending the `--wheel` or `--sdist` flags.

You can install a build by running:

```shell
uv tool install <source>
```

where `<source>` is the path to a wheel, source distribution, or your copy
of the repository.
