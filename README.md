# Celty

Celty generates short-lived GitHub access tokens from the command line.

![gif](vhs/gifs/minimal.gif)

<!-- pre-installation -->

## Installation

### As a binary

Standalone, [attested](https://github.com/celsiusnarhwal/celty/attestations), binaries are distributed for 
macOS ([Apple silicon](https://support.apple.com/en-us/116943) only), Linux, and Windows. 

[mise](https://mise.jdx.dev) is recommended, as it will automatically download the correct binary for your platform and make
it easy to upgrade to new versions of Celty as they are available:

```shell
mise use -g github:celsiusnarhwal/celty
```

Alternatively, you can download a binary from the [releases page](https://github.com/celsiusnarhwal/celty/releases).

### As a Python package

Celty is available [on PyPI](https://pypi.org/project/celty). If you get Celty from PyPI because the binary that was supposed to work on your system
didn't, please [open an issue](https://github.com/celsiusnarhwal/celty/issues/).

#### [uv](https://docs.astral.sh/uv) (recommended)

```shell
uv tool install celty
```

<details>
<summary>Other methods</summary>

#### [pipx](https://pipx.pypa.io)

```shell
pipx install celty
```

#### pip

```shell
pip install celty
```

</details>

### From source

See [SOURCE.md](SOURCE.md).

<!-- post-installation -->

## Usage

Celty's primary command is `celty get`. Given the client ID of a [GitHub App](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/about-creating-github-apps),
`celty get` will have you authenticate with GitHub and print the resulting token to standard output.

### The bare minimum
1. [Create a GitHub App.](https://github.com/settings/apps/new) Make sure **Enable Device Flow** is checked. For permissions:
   - If you only need read access to public repositories, you don't need to set any permissions.
   - If you need read access to private repositories, **Repository permissions** > **Contents** must be set to at least **Read-only**.
   - If you need write access to *any* repositories, private or public, **Repository permissions** > **Contents** must be set to **Read and write**.
      - If you need write access to [workflow](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflows) files, you must *also* set **Repository permissions** > **Workflows** to **Read and write**.
   
   You can configure the other settings however you like.
2. Take note of your app's client ID.
3. Install your app on your account. If you set any repository permissions, you'll need to choose which repositories the app should have access to.
4. Run the following, replacing `<client-id>` with your app's client ID.

   ```shell
   celty get --client-id <client-id>
   ```

### The configuration file

If you need to be able to authenticate with more than one app, you can use a configuration file. Celty's configuration file is written in YAML and looks like this:

```yaml
apps:
   - name: app-1
     client_id: abcdef
     repo_owner: mona
     github_url: https://github.com
     default: true

   - name: app-2
     client_id: ghijkl

  # and so on...
```

Each app supports the following keys:

| **Key**      | **Description**                                                                                                                | **Required?** | **Default (if not required)** |
|--------------|--------------------------------------------------------------------------------------------------------------------------------|---------------|-------------------------------|
| `name`       | The name of the app. Must be unique.                                                                                           | Yes           |                               |
| `client_id`  | The app's client ID.                                                                                                           | Yes           |                               |
| `repo_owner` | See [Repo-based app switching](#repo-based-app-switching). Must be unique.                                                     | No            | N/A                           |
| `github_url` | The GitHub host this app should use. Only GitHub Enterprise Server users should need to change this from its default.          | No            | `https://github.com`          |
| `default`    | Whether Celty should automatically use this app when no app is explicitly specified. Only one app can have this set to `true`. | No            | `false`                       |

Once you've defined apps, you can tell Celty which one to use with `celty get --app`:

```shell
celty get --app <app-name>
```

If you run `celty get` without providing a client ID or app, it will use the app whose `default` key is set to `true`. If no such app exists, it will use the first app in your configuration file. (This doesn't apply when [repo-based app switching](#repo-based-app-swtching) is in effect.)

#### Configuration file location

Where Celty looks for its configuration file depends on your operating system:

- **macOS / Linux**: `$XDG_CONFIG_HOME/celty/config.yml` if the `XDG_CONFIG_HOME` environment variable is set; otherwise, `~/.config/celty/config.yml`.
- **Windows**: `$env:WIN_PD_OVERRIDE_LOCAL_APPDATA\celty\config.yml` if the `WIN_PD_OVERRIDE_LOCAL_APPDATA` environment variable is set; otherwise, `%LOCALAPPDATA%\celty\config.yml`.

This can be overridden with the `--config-file` option.

### Credential storage

If [Keyring](https://github.com/jaraco/keyring) is installed, Celty will store tokens in and retrieve them from Keyring's configured backend. This allows you to run `celty get` once and not have to go through the authentication flow again until the generated token expires. For most users, no configuration should be required beyond installing Keyring and making sure its available on your system path, but Linux users should double-check Keyring's documentation just to be sure.

You can expicilty tell Celty where Keyring's binary is with `celty get --keyring-path`. If you don't want to use credential storage even if Keyring is installed, use `celty get --no-store`.

#### Minimum validity

When credential storage is being used, it's possible for Celty to retrieve a token that's valid at the time but will
expire too soon to be practically useful. To prevent this, you can use `celty get --minimum-validity`. 
`--minimum-validity` takes a [Go duration string](https://pkg.go.dev/time#ParseDuration) representing the minimum
amount of time for a token retrieved from credential stroage must be valid for; in addition to the standard Go units,
you can also use `d` for day, `w` for week, `mm` for month, and `y` for year.[^1] By default, it's `1h`.

[^1]: 1 day = 24 hours, 1 week = 7 days, 1 month = 30 days, and 1 year = 365 days.

### Git credential helper

Celty can be used as a [Git credential helper](https://git-scm.com/docs/gitcredentials). To set it up, run:

```shell
celty helper --global
```

If you're in a Git repository and only want to configure Celty as the credential helper for that repository, omit the `--global` option.

When Git retrieves credentials from Celty, it will run `celty get`. Any extra options passed to `celty helper` will be passed by Git to `celty get`. This means you can make Celty's credential helper use a specific app or client ID, e.g.:

```shell
celty helper --global --app my-app
celty helper --global --client-id abcdefg
```

![gif](vhs/gifs/git.gif)

> [!warning]
> Celty will remove and supplant any existing credential helpers scoped to GitHub.com or, if applicable, your GitHub Enterprise Server instance. Celty does not currently have a command to unconfigure itself as a credential helper, so if you ever want to do that, it will have to be manually.

### Repo-based app switching

When Celty is invoked as a Git credential helper, it can automatically choose which app to authenticate with based on the owner of relevant repository. For example, if you're working in a repository owned by [@mona](https://github.com/mona) and there's an app in your configuration file whose `repo_owner` is `mona`, Celty will automatically use that app even if you don't explicitly ask for it.

### Environment variables

Most of Celty's command-line options can be set with environmet variables. The name of an environment variable is the
prefix `CELTY_` followed by the uppercase, snake case, name of the corresponding option; for example, the environment 
variable for `celty get --client-id` is `CELTY_CLIENT_ID`. You can view all supported variables in the help messages
for Celty's commands.

Command-line options take precedence over their corresponding envrionment variables if both are set.

## Integrations

Celty can integrate with any program, script, or command that makes use of a GitHub access token provided via standard output. For example:

### Using the [GitHub CLI](https://cli.github.com)

Write a wrapper script that invokes Celty to set the `GH_TOKEN` environment variable, then alias `gh` to it:

```shell
#!/bin/sh

# ~/.local/bin/gh-wrapper

GH_TOKEN=$(celty get) gh "$@"
```
```shell
chmod +x ~/.local/bin/gh-wrapper
alias gh="~/.local/bin/gh-wrapper"
```

### Managing private dotfiles with [chezmoi](https://chezmoi.io)

If your chezmoi-managed dotfiles are hosted in a private repo, Celty can help you install them without needing to create a personal access token:

```shell
GITHUB_TOKEN=$(celty get) chezmoi apply https://git:$GITHUB_TOKEN@github.com/<your-username>/dotfiles
```

Once they're installed, you can configure Celty to be chezmoi's Git credential helper:

```shell
chezmoi cd
celty helper
```

### Authenticating with [mise](https://mise.jdx.dev)

If you're using mise's [GitHub backend](https://mise.jdx.dev/dev-tools/backends/github.html) and are either installing tools from private repositories or running into unauthenticated rate limits, Celty can help.

If Celty was installed with mise:

```shell
mise settings set github.credential_command "$(mise which celty) get"
```

Otherwise:

```shell
mise settings set github.credential_command "celty get"
```

## Acknowledgements

Much of Celty's feature set and interface was inspired by [ghtkn](https://github.com/suzuki-shunsuke/ghtkn).
