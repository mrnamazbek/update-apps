#!/usr/bin/env python3
"""Update macOS tools through their existing distribution channels."""

import argparse
import collections
import concurrent.futures
import contextlib
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "0.1.0"
HOME_DIR = Path.home()
APP_DIRS = (Path("/Applications"), HOME_DIR / "Applications")
FORTI_URL = "https://links.fortinet.com/forticlient/mac/vpnagent"
GITHUB_APPS = {
    "com.mikeli.duobar": ("Mikeli7666/DuoBar", "duobar"),
    "com.kgarg.insomnia": ("krishhgg/Insomnia", "insomnia-keep-awake"),
}
# Match bundle identifiers, never display names (there are unrelated Insomnia apps).
BREW_APPS = {
    "eu.exelban.Stats": "stats",
    "com.caldis.Mos": "mos",
    "com.google.Chrome": "google-chrome",
    "com.microsoft.edgemac": "microsoft-edge",
    "com.anthropic.claudefordesktop": "claude",
    "com.todesktop.230313mzl4w4u92": "cursor",
    "com.docker.docker": "docker-desktop",
    "md.obsidian": "obsidian",
    "com.jetbrains.toolbox": "jetbrains-toolbox",
    "com.jetbrains.datagrip": "datagrip",
    "com.jetbrains.rider": "rider",
    "com.microsoft.teams2": "microsoft-teams",
    "Cisco-Systems.Spark": "webex",
    "com.cisco.Jabber": "cisco-jabber",
    "com.daisydiskapp.DaisyDiskStandAlone": "daisydisk",
    "com.macpaw.site.Gemini2": "gemini",
    "org.tabby": "tabby",
    "com.dbeaver.product.enterprise": "dbeaver-enterprise",
    "com.google.antigravity": "antigravity",
    "io.tailscale.ipn.macsys": "tailscale-app",
    "com.logi.optionsplus": "logi-options+",
}


def capture(args, timeout=120):
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1")
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-1500:])
    return result.stdout


def execute(args):
    print("Running: " + shlex.join(args), file=sys.stderr, flush=True)
    # Keep stdout machine-readable in --json mode; managers own their auth prompts.
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1")
    return subprocess.run(args, stdout=sys.stderr, env=env).returncode


def json_lines(text):
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "update-apps/" + VERSION})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def download_file(url, destination, max_bytes=512 * 1024 * 1024):
    request = urllib.request.Request(url, headers={"User-Agent": "update-apps/" + VERSION})
    with urllib.request.urlopen(request, timeout=60) as response:
        if urllib.parse.urlparse(response.geturl()).scheme != "https":
            raise RuntimeError("Download redirected away from HTTPS")
        with Path(destination).open("xb") as output:
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise RuntimeError("Download exceeds its size limit")
                output.write(chunk)


@contextlib.contextmanager
def update_lock():
    directory = HOME_DIR / "Library/Caches/update-apps"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / "update.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another update-apps mutation is already running")
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def numeric_version(version):
    return tuple(int(part) for part in re.findall(r"\d+", version.split(",")[0]))


def app_info(path):
    plist_path = path / "Contents/Info.plist"
    if not plist_path.is_file():
        wrappers = list((path / "Wrapper").glob("*.app/Info.plist"))
        if not wrappers:
            return None
        plist_path = wrappers[0]
    with plist_path.open("rb") as handle:
        info = plistlib.load(handle)
    receipt_roots = (path / "Contents", plist_path.parent)
    return {
        "name": path.stem, "path": str(path),
        "bundle_id": info.get("CFBundleIdentifier", ""),
        "version": info.get("CFBundleShortVersionString") or info.get("CFBundleVersion", "unknown"),
        "app_store": any((root / "_MASReceipt/receipt").exists() for root in receipt_roots),
        "update_feed": info.get("SUFeedURL", ""),
    }


def discover():
    brew = json.loads(capture(["brew", "info", "--json=v2", "--installed"]))
    store_apps = json_lines(capture(["mas", "list", "--json"]))
    store_ids = {entry.get("bundleID") for entry in store_apps}
    managed_names = {}
    for cask in brew.get("casks", []):
        for artifact in cask.get("artifacts", []):
            if "app" in artifact:
                managed_names[Path(artifact["app"][0]).name] = cask["token"]
    apps = []
    for root in APP_DIRS:
        paths = list(root.glob("*.app")) + list(root.glob("*/*.app"))
        for path in paths:
            try:
                app = app_info(path)
            except (OSError, plistlib.InvalidFileException):
                continue
            if not app or "uninstall" in app["name"].lower():
                continue
            bundle_id = app["bundle_id"]
            if app["app_store"] or bundle_id in store_ids:
                app.update(source="app-store", updater="mas")
            elif path.name in managed_names and root == APP_DIRS[0]:
                app.update(source="homebrew", updater=managed_names[path.name])
            elif bundle_id in GITHUB_APPS:
                app.update(source="github", updater=GITHUB_APPS[bundle_id][1])
            elif bundle_id == "com.fortinet.FortiClient":
                app.update(source="fortinet", updater="forticlient-vpn")
            elif bundle_id in BREW_APPS and path.parent == Path("/Applications"):
                app.update(source="homebrew-candidate", updater=BREW_APPS[bundle_id])
            elif "/System/" in str(path.resolve()):
                app.update(source="macos", updater="macOS Software Update")
            elif (path / "Wrapper").is_dir():
                app.update(source="app-store-ios", updater="App Store app (MAS does not support iOS apps)")
            else:
                app.update(source="vendor", updater="app's own updater")
            apps.append(app)
    return {
        "apps": sorted(apps, key=lambda app: app["name"].casefold()),
        "counts": dict(collections.Counter(app["source"] for app in apps)),
        "homebrew_casks": [cask["token"] for cask in brew.get("casks", [])],
        "homebrew_formulae": [formula["name"] for formula in brew.get("formulae", [])],
    }


def release_status(app):
    repo, _ = GITHUB_APPS[app["bundle_id"]]
    release = get_json("https://api.github.com/repos/" + repo + "/releases/latest")
    if release.get("draft") or release.get("prerelease"):
        raise RuntimeError("GitHub's latest endpoint returned an unstable release")
    latest = release["tag_name"].lstrip("v")
    return {"name": app["name"], "installed": app["version"], "latest": latest,
            "update_available": numeric_version(latest) > numeric_version(app["version"]),
            "url": release["html_url"], "release": release}


def forti_status(app):
    request = urllib.request.Request(FORTI_URL, method="HEAD")
    with urllib.request.urlopen(request, timeout=30) as response:
        url = response.geturl()
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.hostname != "filestore.fortinet.com":
        raise RuntimeError("Fortinet download redirected to an unexpected host")
    match = re.search(r"FortiClientVPN_(\d+\.\d+\.\d+\.\d+)_OnlineInstaller\.dmg", url)
    if not match:
        raise RuntimeError("Fortinet changed its download format; inspect the official site")
    latest = match.group(1)
    # Fortinet's March 2026 release 4323 is newer than the December 2025 build 6667.
    known_transition = (app["version"], latest) == ("7.4.3.6667", "7.4.3.4323")
    newer = numeric_version(latest) > numeric_version(app["version"]) or known_transition
    return {"name": app["name"], "installed": app["version"], "latest": latest,
            "update_available": newer, "download_url": url,
            "review_required": latest != app["version"] and not newer,
            "note": "Official VPN-only channel; unknown lower build numbers require review."}


def check_updates(inventory):
    checks, errors = [], []
    for source, command in (
        ("homebrew", ["brew", "outdated", "--json=v2", "--greedy"]),
        ("app-store", ["mas", "outdated", "--json"]),
    ):
        try:
            output = capture(command)
            data = json.loads(output) if source == "homebrew" else json_lines(output)
            checks.append({"source": source, "outdated": data})
        except Exception as error:
            errors.append({"source": source, "error": str(error)})
    for app in inventory["apps"]:
        if app["source"] not in ("github", "fortinet"):
            continue
        try:
            status = release_status(app) if app["source"] == "github" else forti_status(app)
            status.pop("release", None)
            checks.append({"source": app["source"], **status})
        except Exception as error:
            errors.append({"source": app["name"], "error": str(error)})
    candidates = [app for app in inventory["apps"] if app["source"] == "homebrew-candidate"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {pool.submit(cask_status, app): app for app in candidates}
        for future, app in tasks.items():
            try:
                checks.append({"source": "homebrew-candidate", **future.result()})
            except Exception as error:
                errors.append({"source": app["name"], "error": str(error)})
    return {"counts": inventory["counts"], "checks": checks, "errors": errors,
            "adoption_candidates": candidates,
            "vendor_managed": [app for app in inventory["apps"] if app["source"] in ("vendor", "macos", "app-store-ios")]}


def cask_status(app):
    casks = json.loads(capture(["brew", "info", "--cask", "--json=v2", app["updater"]]))["casks"]
    cask = casks[0]
    artifacts = cask.get("artifacts", [])
    names = [Path(item["app"][0]).name for item in artifacts if "app" in item]
    if Path(app["path"]).name not in names or any("pkg" in item or "installer" in item for item in artifacts):
        return {"name": app["name"], "installed": app["version"], "latest": cask["version"],
                "adoptable": False, "reason": "Vendor package requires its own installer"}
    latest = cask.get("bundle_short_version") or cask["version"].split(",")[0]
    return {"name": app["name"], "installed": app["version"], "latest": str(latest),
            "update_available": numeric_version(str(latest)) > numeric_version(app["version"]),
            "adoptable": str(latest) == str(app["version"])}


def safe_adopt(app, dry_run=False):
    status = cask_status(app)
    if not status["adoptable"]:
        return {"name": app["name"], "status": "action_required",
                "reason": status.get("reason", "Update with the app's updater first, then rerun to adopt without replacement"),
                "installed": app["version"], "latest": status["latest"]}
    if dry_run:
        return {"name": app["name"], "status": "would_adopt", "version": status["latest"]}
    code = execute(["brew", "install", "--cask", "--adopt", app["updater"]])
    return {"name": app["name"], "status": "adopted" if code == 0 else "action_required",
            "reason": "Homebrew verifies an exact match; existing app is never forcibly replaced"}


def verify_app(bundle, bundle_id, team_id):
    info = app_info(bundle)
    if not info or info["bundle_id"] != bundle_id:
        raise RuntimeError("Downloaded app does not match the installed bundle identifier")
    capture(["codesign", "--verify", "--deep", "--strict", str(bundle)])
    requirement = 'anchor apple generic and certificate leaf[subject.OU] = "' + team_id + '"'
    capture(["codesign", "--verify", "--strict", "-R", requirement, str(bundle)])
    capture(["spctl", "--assess", "--type", "execute", str(bundle)])
    return info


def duobar_update(app):
    status = release_status(app)
    if not status["update_available"]:
        return {"name": app["name"], "status": "current", "version": app["version"]}
    assets = [asset for asset in status["release"]["assets"] if re.fullmatch(r"DuoBar-[\d.]+\.dmg", asset["name"])]
    if len(assets) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", assets[0].get("digest") or ""):
        raise RuntimeError("DuoBar release needs a single DMG with a published SHA-256")
    asset = assets[0]
    url = asset["browser_download_url"]
    if not url.startswith("https://github.com/Mikeli7666/DuoBar/releases/download/"):
        raise RuntimeError("Unexpected DuoBar download source")
    root = Path(tempfile.mkdtemp(prefix="update-apps-"))
    mounted = False
    image_path, mount, staging = root / "release.dmg", root / "mounted", root / "DuoBar.app"
    try:
        download_file(url, image_path)
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != asset["digest"].split(":")[1]:
            raise RuntimeError("DuoBar checksum mismatch")
        capture(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(image_path)])
        mounted = True
        info = verify_app(mount / "DuoBar.app", app["bundle_id"], "M42BR3TVW4")
        if info["version"] != status["latest"]:
            raise RuntimeError("DuoBar bundle version does not match its release")
        capture(["ditto", str(mount / "DuoBar.app"), str(staging)])
        if not os.access(Path(app["path"]).parent, os.W_OK) or not os.access(HOME_DIR / ".Trash", os.W_OK):
            raise RuntimeError("App or Trash directory is not writable; no app was closed or replaced")
        was_running = subprocess.run(["pgrep", "-x", "DuoBar"], stdout=subprocess.DEVNULL).returncode == 0
        if was_running:
            subprocess.run(["pkill", "-TERM", "-x", "DuoBar"], check=True)
            for _ in range(10):
                if subprocess.run(["pgrep", "-x", "DuoBar"], stdout=subprocess.DEVNULL).returncode:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("DuoBar did not quit; no files replaced")
        trash = HOME_DIR / ".Trash" / ("DuoBar-" + app["version"] + "-" + str(time.time_ns()) + ".app")
        try:
            Path(app["path"]).rename(trash)
        except Exception:
            if was_running:
                subprocess.run(["open", "-a", app["path"]])
            raise
        try:
            staging.rename(app["path"])
        except Exception:
            trash.rename(app["path"])
            if was_running:
                subprocess.run(["open", "-a", app["path"]])
            raise
        if was_running:
            capture(["open", "-a", app["path"]])
        return {"name": app["name"], "status": "updated", "version": info["version"], "previous_app": str(trash)}
    finally:
        if mounted:
            # Preserve the directory and image if macOS cannot eject the volume.
            if subprocess.run(["hdiutil", "detach", str(mount)], stdout=sys.stderr).returncode:
                raise RuntimeError("Could not eject DuoBar image; files retained at " + str(root))
        shutil.rmtree(root)


def vendor_update(app):
    if app["source"] == "github":
        status = release_status(app)
        if not status["update_available"]:
            return {"name": app["name"], "status": "current", "version": app["version"]}
        # Insomnia also upgrades a recovery agent and sudoers rule: use its own instructions.
        capture(["open", status["url"]])
        return {"name": app["name"], "status": "action_required", "url": status["url"],
                "reason": "Finish the official Insomnia installer, including its recovery-agent checks"}
    status = forti_status(app)
    if status["review_required"]:
        return {"name": app["name"], "status": "action_required",
                "reason": "Fortinet published an unfamiliar lower build number; review before replacing the app",
                "installed": app["version"], "latest": status["latest"]}
    if not status["update_available"]:
        return {"name": app["name"], "status": "current", "version": app["version"]}
    connections = capture(["scutil", "--nc", "list"])
    if any("fortinet" in line.lower() and "(Disconnected)" not in line for line in connections.splitlines()):
        return {"name": app["name"], "status": "action_required", "reason": "Disconnect FortiClient VPN before updating"}
    root = Path(tempfile.mkdtemp(prefix="update-apps-fortinet-"))
    os.chmod(root, 0o700)
    conf = Path("/Library/Application Support/Fortinet/FortiClient/conf")
    if conf.is_dir():
        capture(["ditto", str(conf), str(root / "settings-backup")])
        os.chmod(root / "settings-backup", 0o700)
    image_path, mount = root / "installer.dmg", root / "mounted"
    download_file(status["download_url"], image_path)
    capture(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(image_path)])
    installer = mount / "FortiClientInstaller.app"
    verify_app(installer, "com.fortinet.fct.FortiClientInstaller", "AH4XFXJ7DK")
    capture(["open", "-a", str(installer)])
    return {"name": app["name"], "status": "action_required", "version": status["latest"],
            "reason": "Finish the open Fortinet installer and macOS administrator authentication",
            "installer_directory": str(root), "settings_backup": str(root / "settings-backup")}


def update(inventory):
    results = []
    if execute(["brew", "update"]) != 0:
        return {"results": [], "errors": ["Homebrew metadata update failed; no app updates attempted"]}
    for app in inventory["apps"]:
        if app["source"] == "homebrew-candidate":
            try:
                results.append(safe_adopt(app))
            except Exception as error:
                results.append({"name": app["name"], "status": "action_required", "reason": str(error)})
    for source, command in (
        ("homebrew-formulae", ["brew", "upgrade", "--formula"]),
        ("homebrew-casks", ["brew", "upgrade", "--cask", "--greedy"]),
        ("app-store", ["mas", "update"]),
    ):
        code = execute(command)
        results.append({"name": source, "status": "completed" if code == 0 else "failed", "exit_code": code})
    for app in inventory["apps"]:
        if app["source"] not in ("github", "fortinet"):
            continue
        try:
            result = duobar_update(app) if app["updater"] == "duobar" else vendor_update(app)
            results.append(result)
        except Exception as error:
            results.append({"name": app["name"], "status": "failed", "reason": str(error)})
    return {"results": results, "vendor_managed": [app for app in inventory["apps"] if app["source"] in ("vendor", "macos", "app-store-ios")]}


def doctor():
    tools = {}
    for name in ("brew", "mas", "codesign", "spctl", "hdiutil"):
        tools[name] = shutil.which(name)
    return {"version": VERSION, "python": sys.executable, "tools": tools,
            "auth": "Delegated to Homebrew, the Mac App Store and vendor installers; no credentials stored",
            "ready": sys.platform == "darwin" and all(tools.values())}


def human_output(data):
    if "apps" in data:
        for app in data["apps"]:
            print("{:<25} {:<17} {:<21} {}".format(app["name"], app["version"], app["source"], app["updater"]))
        print("\nCoverage: " + ", ".join("{} {}".format(count, source) for source, count in data["counts"].items()))
    elif "checks" in data:
        for item in data["checks"]:
            if "name" in item:
                note = " — update available" if item.get("update_available") else ""
                if item.get("review_required"):
                    note += " — release ordering needs review"
                if item["source"] == "homebrew-candidate":
                    note += " — can adopt" if item["adoptable"] else " — vendor action needed"
                print("{}: {} (latest {}){}".format(item["name"], item["installed"], item["latest"], note))
            else:
                print(item["source"] + " pending updates:")
                groups = item["outdated"]
                entries = (groups.get("formulae", []) + groups.get("casks", [])) if isinstance(groups, dict) else groups
                if not entries:
                    print("  None")
                for entry in entries:
                    name = entry.get("name") or entry.get("displayName") or str(entry.get("adamID", "app"))
                    installed = entry.get("installed_versions") or entry.get("installed_version") or entry.get("version", "")
                    latest = entry.get("current_version") or entry.get("latestVersion") or "App Store update"
                    if isinstance(installed, list):
                        installed = ", ".join(installed)
                    print("  {}: {} -> {}".format(name, installed, latest))
        for error in data["errors"]:
            print("Check failed: " + json.dumps(error))
        print("\n{} Homebrew adoption candidates; {} apps use their vendor's own updater.".format(len(data["adoption_candidates"]), len(data["vendor_managed"])))
        print("Use update-apps list for exact coverage. Checks never install updates.")
    elif "results" in data:
        for item in data["results"]:
            print("{}: {}{}".format(item["name"], item["status"], " — " + item["reason"] if item.get("reason") else ""))
        if data.get("vendor_managed"):
            print("Vendor-managed apps not updated: " + ", ".join(app["name"] for app in data["vendor_managed"]))
        for error in data.get("errors", []):
            print(error)
    else:
        print(json.dumps(data, indent=2))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    parser = argparse.ArgumentParser(prog="update-apps", description="Update installed macOS tools through MAS, Homebrew and verified vendor sources. With no subcommand, update all supported tools.")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--json", action="store_true", help="Emit a stable JSON envelope (also accepted after subcommands)")
    subs = parser.add_subparsers(dest="command")
    subs.add_parser("doctor", help="Check required tools and explain authentication")
    subs.add_parser("list", help="List installed apps, identities and updater coverage")
    subs.add_parser("check", help="Read pending updates without changing apps")
    resolve = subs.add_parser("resolve", help="Resolve an installed app name or bundle identifier")
    resolve.add_argument("name")
    apply = subs.add_parser("update", help="Update managed tools and start necessary vendor installers")
    apply.add_argument("--dry-run", action="store_true", help="Check only; install nothing")
    adopt = subs.add_parser("adopt", help="Register matching existing desktop apps with Homebrew")
    adopt.add_argument("names", nargs="*", help="Exact app name, bundle ID or cask token; default: all candidates")
    adopt.add_argument("--dry-run", action="store_true", help="Preview adoption without changing package registrations")
    request = subs.add_parser("request", help="Read a public GitHub or Homebrew JSON endpoint")
    request.add_argument("url")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        if error.code and as_json:
            print(json.dumps({"ok": False, "error": {"type": "ArgumentError", "message": "Invalid arguments; run update-apps --help"}}))
            return int(error.code)
        raise
    try:
        command = args.command or "update"
        read_only = command in ("doctor", "request", "list", "resolve", "check") or getattr(args, "dry_run", False)
        if command not in ("doctor", "request") and sys.platform != "darwin":
            raise RuntimeError("App management requires macOS; --help and doctor work on other platforms")
        if not read_only and os.geteuid() == 0:
            raise RuntimeError("Run update-apps as your normal user; package managers request administrator access when needed")
        if command == "doctor":
            data = doctor()
        elif command == "request":
            parsed = urllib.parse.urlparse(args.url)
            if parsed.scheme != "https" or parsed.hostname not in ("api.github.com", "formulae.brew.sh") or parsed.username or parsed.password:
                raise ValueError("Raw reads are restricted to public GitHub and Homebrew HTTPS JSON endpoints")
            data = get_json(args.url)
        else:
            inventory = discover()
            if command == "list":
                data = inventory
            elif command == "resolve":
                matches = [app for app in inventory["apps"] if args.name.casefold() in (app["name"].casefold(), app["bundle_id"].casefold(), app["updater"].casefold())]
                if not matches:
                    raise ValueError("No installed app matches " + args.name)
                data = {"matches": matches}
            elif command == "adopt":
                candidates = [app for app in inventory["apps"] if app["source"] == "homebrew-candidate"]
                if args.names:
                    selected = set(name.casefold() for name in args.names)
                    candidates = [app for app in candidates if selected.intersection((app["name"].casefold(), app["bundle_id"].casefold(), app["updater"].casefold()))]
                    matched = {value.casefold() for app in candidates for value in (app["name"], app["bundle_id"], app["updater"])}
                    if not selected.issubset(matched):
                        raise ValueError("Unknown or already managed adoption target: " + ", ".join(sorted(selected - matched)))
                lock = contextlib.nullcontext() if args.dry_run else update_lock()
                with lock:
                    data = {"results": [safe_adopt(app, args.dry_run) for app in candidates]}
            elif command == "check" or getattr(args, "dry_run", False):
                data = check_updates(inventory)
            else:
                with update_lock():
                    data = update(inventory)
        incomplete = bool(data.get("errors")) or any(item.get("status") in ("failed", "action_required") for item in data.get("results", []))
        if "ready" in data and not data["ready"]:
            incomplete = True
        if as_json:
            print(json.dumps({"ok": not incomplete, "data": data}))
        else:
            human_output(data)
        return 2 if incomplete else 0
    except Exception as error:
        if as_json:
            print(json.dumps({"ok": False, "error": {"type": type(error).__name__, "message": str(error)}}))
        else:
            print("update-apps: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
