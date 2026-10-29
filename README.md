# update-apps

One command to update your macOS tools across Homebrew, the Mac App Store, and
selected developer sources.

```sh
update-apps check    # See available updates
update-apps          # Run supported updates
update-apps list     # See which updater manages each app
```

`update-apps` is an independent orchestrator. It calls **Homebrew** and **MAS**;
it does not fork or modify them. Direct-download apps cannot be added to MAS.
This early release makes the boundary visible: automatic updates, adoption
candidates, vendor-installer steps, and unsupported apps are reported separately.

## Install

Requires macOS, Python 3.9+, [Homebrew](https://brew.sh), and
[MAS 7+](https://github.com/mas-cli/mas). Sign in to the Mac App Store to update
store apps. The Python program itself has no third-party runtime dependencies.

```sh
brew install mas
git clone https://github.com/mrnamazbek/update-apps.git
cd update-apps
make install-local
```

The command is installed into `~/.local/bin`. Add that directory to your shell's
`PATH` if necessary, then open a new Terminal. To choose another directory:

```sh
make install-local BIN_DIR=/your/bin/directory
```

Alternatively, install from the checkout with `uv tool install .` or inside a
Python virtual environment with `python3 -m pip install .`. No PyPI release is
currently published by this project.

Run it as your normal user, **not** with `sudo`. Homebrew, MAS, and vendor
installers request their own authentication when required. No background service
or recurring task is installed.

## Coverage

| Source | Behavior |
| --- | --- |
| Installed Homebrew formulae | Runs `brew upgrade --formula` |
| Installed Homebrew casks | Runs `brew upgrade --cask --greedy`, including self-updating casks |
| Eligible Mac App Store apps | Runs `mas update` |
| Recognized manual desktop apps | Attempts conservative Homebrew adoption; see below |
| DuoBar | Checks stable releases and installs a verified app update |
| Insomnia keep-awake utility | Checks stable releases; opens vendor instructions when an update is needed |
| FortiClient VPN-only | Checks the official download; opens its verified installer when an update is needed |
| Other vendor-managed apps | Listed explicitly; use their existing updater |
| macOS system apps and iOS/iPadOS apps | Listed separately; this command does not update them |

Run `update-apps list` for the actual coverage on your Mac. This is not a promise
that every installed application can be updated automatically.

### Adopting existing apps

Some apps are supported by Homebrew but were installed manually. The tool matches
known **bundle identifiers**, not display names, and attempts adoption only when
the installed version already matches the current cask. Homebrew must also verify
the existing app's contents before registering it.

```sh
update-apps adopt stats --dry-run
update-apps adopt stats
```

If versions differ, contents do not match, or a cask requires a native installer,
the tool reports `action_required`. Update that app through its own updater first,
then rerun adoption. There is no forced replacement, edition switch, or automatic
uninstallation to bypass a mismatch.

The mapping includes tools such as Stats, Mos, Chrome, Edge, Obsidian, Cursor,
JetBrains Toolbox, and others. It preserves existing Homebrew pins, tap trust,
and selected stable/beta casks.

### Developer-specific utilities

**DuoBar:** a newer stable release must have a published SHA-256, the correct
bundle identifier, the expected Apple Developer ID, and Gatekeeper acceptance.
Only its app bundle is replaced; the previous bundle is moved to Trash. A failed
replacement restores the previous app. Preferences remain outside that operation.

**Insomnia:** this integration targets
[`krishhgg/Insomnia`](https://github.com/krishhgg/Insomnia), bundle identifier
`com.kgarg.insomnia`. It is the keep-awake utility, not Kong's HTTP client with
the same display name. Its own installer also manages a recovery agent and a
sudoers rule, so an available update opens its release-specific instructions
and remains `action_required` until completed separately.

**FortiClient:** uses Fortinet's official VPN-only download, rather than replacing
the free client with a paid edition. It checks that the VPN is disconnected,
backs up configuration, verifies the downloader's signing identity and Gatekeeper
acceptance, and opens the official installer. Complete the macOS authentication
and vendor installation steps yourself. The result reports the protected backup
and temporary installer directory. A restart can be needed to remove an old VPN
extension. Unknown lower build numbers require review; the documented
`7.4.3.6667 → 7.4.3.4323` re-release is recognized explicitly.

## Commands

```sh
update-apps                              # Update all supported tools
update-apps check                        # Read-only preview
update-apps update --dry-run              # Same preview
update-apps list                         # Inventory and update sources
update-apps resolve Insomnia              # Resolve an installed app's identity
update-apps adopt stats --dry-run          # Preview Homebrew adoption
update-apps adopt stats                   # Register an exact matching app
update-apps --json doctor                 # Dependencies and auth requirements
update-apps --json check                  # Machine-readable preview
update-apps request https://api.github.com/repos/Caldis/Mos/releases/latest
```

`--json` works before or after the subcommand. The raw `request` escape hatch
performs HTTPS GET requests only to public GitHub or Homebrew JSON endpoints.

Updates can close running applications and change installed packages. Preview
first when deciding when to update work tools. No VPN connection or reboot is
initiated automatically. Concurrent mutating invocations are blocked by a local
lock in `~/Library/Caches/update-apps/`.

## JSON, exit codes, and authentication

The CLI owns the outer envelope; provider-specific data is nested under `data`:

```json
{"ok": true, "data": {"matches": []}}
```

Failures use a structured error, or per-provider results for partial completion:

```json
{"ok": false, "error": {"type": "RuntimeError", "message": "Explanation"}}
```

```json
{"ok": false, "data": {"results": [{"name": "FortiClient", "status": "action_required", "reason": "Finish the vendor installer"}]}}
```

Progress and package-manager output go to stderr. Exit codes:

- `0`: the read or supported operation completed.
- `1`: fatal runtime or request error.
- `2`: invalid arguments, incomplete checks, failed provider operation, or user action required.

Vendor-managed exclusions are always listed; exit `0` does not mean those apps
were updated. The CLI stores no credentials. MAS uses the existing App Store
account; package managers and vendor installers manage their own authentication.
Public GitHub checks are unauthenticated and subject to GitHub's rate limit.
Check-only commands may refresh metadata or caches but do not install updates.

## Development

```sh
make test
```

Tests use temporary app fixtures and mocked network/package-manager calls. They
do not install real updates. CI tests Python 3.11 and 3.13 on macOS and Linux;
Linux supports the test suite, help, and dependency diagnostics, not app management.

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and the
[MIT license](LICENSE). No third-party app binaries or VPN settings are distributed.

## Upstream documentation

- [MAS commands and platform limitations](https://github.com/mas-cli/mas#commands)
- [Homebrew adoption](https://docs.brew.sh/Tips-and-Tricks#appoint-homebrew-cask-to-manage-a-manually-installed-app)
- [Homebrew upgrade options](https://docs.brew.sh/Manpage)
- [DuoBar releases](https://github.com/Mikeli7666/DuoBar/releases)
- [Insomnia installation](https://github.com/krishhgg/Insomnia/blob/main/docs/install.md)
- [Fortinet downloads](https://www.fortinet.com/support/product-downloads)
