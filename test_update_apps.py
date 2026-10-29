import contextlib
import io
import json
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import update_apps as app


class AppUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def bundle(self, name, identifier, version):
        bundle = self.root / (name + ".app")
        (bundle / "Contents").mkdir(parents=True)
        with (bundle / "Contents/Info.plist").open("wb") as handle:
            plistlib.dump({"CFBundleIdentifier": identifier, "CFBundleShortVersionString": version}, handle)
        return bundle

    def forti_response(self, version, host="filestore.fortinet.com"):
        response = Mock()
        response.geturl.return_value = "https://" + host + "/forticlient/downloads/FortiClientVPN_" + version + "_OnlineInstaller.dmg"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_installed_insomnia_resolves_to_keep_awake_project(self):
        bundle = self.bundle("Insomnia", "com.kgarg.insomnia", "0.1.0")
        with patch.object(app, "APP_DIRS", (self.root, self.root / "absent")), patch.object(app, "capture", side_effect=[json.dumps({"casks": [], "formulae": []}), ""]):
            inventory = app.discover()
        self.assertEqual(inventory["apps"][0]["source"], "github")
        self.assertEqual(inventory["apps"][0]["updater"], "insomnia-keep-awake")
        self.assertEqual(app.app_info(bundle)["bundle_id"], "com.kgarg.insomnia")
        self.assertNotIn("com.kgarg.insomnia", app.BREW_APPS)

    def test_app_store_receipt_takes_precedence_over_homebrew_candidate(self):
        bundle = self.bundle("Stats", "eu.exelban.Stats", "3.0.23")
        receipt = bundle / "Contents/_MASReceipt"
        receipt.mkdir()
        (receipt / "receipt").touch()
        with patch.object(app, "APP_DIRS", (self.root, self.root / "absent")), patch.object(app, "capture", side_effect=[json.dumps({"casks": [], "formulae": []}), ""]):
            inventory = app.discover()
        self.assertEqual(inventory["apps"][0]["source"], "app-store")

    def test_mas_ndjson_and_empty_results(self):
        self.assertEqual(app.json_lines('{"adamID":1}\n{"adamID":2}\n'), [{"adamID": 1}, {"adamID": 2}])
        self.assertEqual(app.json_lines(""), [])

    def test_fortinet_documented_lower_number_is_newer(self):
        with patch.object(app.urllib.request, "urlopen", return_value=self.forti_response("7.4.3.4323")):
            result = app.forti_status({"name": "FortiClient", "version": "7.4.3.6667"})
        self.assertTrue(result["update_available"])
        self.assertFalse(result["review_required"])

    def test_fortinet_unknown_lower_build_requires_review(self):
        with patch.object(app.urllib.request, "urlopen", return_value=self.forti_response("7.4.3.1000")):
            result = app.forti_status({"name": "FortiClient", "version": "7.4.3.4323"})
        self.assertFalse(result["update_available"])
        self.assertTrue(result["review_required"])

    def test_fortinet_redirect_to_another_vendor_is_rejected(self):
        with patch.object(app.urllib.request, "urlopen", return_value=self.forti_response("7.4.3.4323", "example.com")):
            with self.assertRaisesRegex(RuntimeError, "unexpected host"):
                app.forti_status({"name": "FortiClient", "version": "7.4.3.6667"})

    def test_older_manual_app_is_not_forcibly_replaced(self):
        data = {"casks": [{"version": "3.0.24", "artifacts": [{"app": ["Stats.app"]}]}]}
        installed = {"name": "Stats", "path": "/Applications/Stats.app", "version": "3.0.23", "updater": "stats"}
        with patch.object(app, "capture", return_value=json.dumps(data)), patch.object(app, "execute") as execute:
            result = app.safe_adopt(installed)
        self.assertEqual(result["status"], "action_required")
        execute.assert_not_called()

    def test_native_packages_are_not_run_during_adoption(self):
        data = {"casks": [{"version": "1", "artifacts": [{"app": ["Tool.app"]}, {"pkg": ["Install.pkg"]}]}]}
        installed = {"name": "Tool", "path": "/Applications/Tool.app", "version": "1", "updater": "tool"}
        with patch.object(app, "capture", return_value=json.dumps(data)), patch.object(app, "execute") as execute:
            result = app.safe_adopt(installed)
        self.assertEqual(result["status"], "action_required")
        execute.assert_not_called()

    def test_matching_adoption_uses_adopt_without_force(self):
        data = {"casks": [{"version": "3.0.23", "artifacts": [{"app": ["Stats.app"]}]}]}
        installed = {"name": "Stats", "path": "/Applications/Stats.app", "version": "3.0.23", "updater": "stats"}
        with patch.object(app, "capture", return_value=json.dumps(data)), patch.object(app, "execute", return_value=0) as execute:
            self.assertEqual(app.safe_adopt(installed)["status"], "adopted")
        execute.assert_called_once_with(["brew", "install", "--cask", "--adopt", "stats"])

    def test_dry_run_never_runs_update_or_adoption(self):
        output = io.StringIO()
        with patch.object(app.sys, "platform", "darwin"), patch.object(app, "discover", return_value={}), patch.object(app, "check_updates", return_value={"checks": [], "errors": []}), patch.object(app, "update") as update, contextlib.redirect_stdout(output):
            code = app.main(["--json", "update", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["ok"])
        update.assert_not_called()

    def duobar_release(self):
        return {"update_available": True, "latest": "1.3.3", "release": {"assets": [{
            "name": "DuoBar-1.3.3.dmg", "digest": "sha256:" + "0" * 64,
            "browser_download_url": "https://github.com/Mikeli7666/DuoBar/releases/download/v1.3.3/DuoBar-1.3.3.dmg",
        }]}}

    def test_checksum_failure_cannot_replace_installed_duobar(self):
        bundle = self.bundle("DuoBar", "com.mikeli.duobar", "1.3.2")
        installed = app.app_info(bundle)
        def fake_download(url, destination):
            Path(destination).write_bytes(b"incorrect download")
        with patch.object(app, "release_status", return_value=self.duobar_release()), patch.object(app, "download_file", side_effect=fake_download), patch.object(app, "capture") as capture:
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                app.duobar_update(installed)
        capture.assert_not_called()
        self.assertTrue(bundle.is_dir())
        self.assertEqual(app.app_info(bundle)["version"], "1.3.2")

    def test_detach_failure_retains_temporary_directory(self):
        staging_root = self.root / "staging"
        staging_root.mkdir()
        data = self.duobar_release()
        data["release"]["assets"][0]["digest"] = "sha256:" + app.hashlib.sha256(b"data").hexdigest()
        def fake_download(url, destination):
            Path(destination).write_bytes(b"data")
        with patch.object(app, "release_status", return_value=data), patch.object(app.tempfile, "mkdtemp", return_value=str(staging_root)), patch.object(app, "download_file", side_effect=fake_download), patch.object(app, "capture", return_value=""), patch.object(app, "verify_app", side_effect=RuntimeError("not notarized")), patch.object(app.subprocess, "run", return_value=Mock(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, "files retained"):
                app.duobar_update({"name": "DuoBar", "version": "1.3.2", "bundle_id": "com.mikeli.duobar"})
        self.assertTrue(staging_root.is_dir())

    def test_failed_atomic_replacement_restores_the_original_app(self):
        installed_path = self.bundle("DuoBar", "com.mikeli.duobar", "1.3.2")
        staging_root = self.root / "staging"
        staging_root.mkdir()
        (self.root / ".Trash").mkdir()
        data = self.duobar_release()
        data["release"]["assets"][0]["digest"] = "sha256:" + app.hashlib.sha256(b"data").hexdigest()
        original_rename = Path.rename
        def fake_download(url, destination):
            Path(destination).write_bytes(b"data")
        def fake_capture(command):
            if command[0] == "ditto":
                app.shutil.copytree(installed_path, command[-1])
            return ""
        def failing_rename(source, target):
            if source == staging_root / "DuoBar.app":
                raise OSError("simulated cross-device rename failure")
            return original_rename(source, target)
        with patch.object(app, "HOME_DIR", self.root), patch.object(app, "release_status", return_value=data), patch.object(app.tempfile, "mkdtemp", return_value=str(staging_root)), patch.object(app, "download_file", side_effect=fake_download), patch.object(app, "capture", side_effect=fake_capture), patch.object(app, "verify_app", return_value={"version": "1.3.3"}), patch.object(app.subprocess, "run", return_value=Mock(returncode=1)) as run, patch.object(Path, "rename", failing_rename):
            # pgrep=1 means the app was not running; detach must succeed.
            run.side_effect = lambda command, **kwargs: Mock(returncode=0 if command[0] == "hdiutil" else 1)
            with self.assertRaisesRegex(OSError, "cross-device"):
                app.duobar_update(app.app_info(installed_path))
        self.assertEqual(app.app_info(installed_path)["version"], "1.3.2")
        self.assertEqual(list((self.root / ".Trash").iterdir()), [])

    def test_json_argument_errors_are_machine_readable(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = app.main(["--json", "invalid-command"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output.getvalue())["ok"])

    def test_raw_request_cannot_send_credentials_to_an_arbitrary_host(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(app, "get_json") as request:
            code = app.main(["--json", "request", "https://token@example.com/data"])
        self.assertEqual(code, 1)
        request.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())["ok"])

    def test_non_macos_mutation_is_rejected_before_discovery(self):
        output = io.StringIO()
        with patch.object(app.sys, "platform", "linux"), patch.object(app, "discover") as discover, contextlib.redirect_stdout(output):
            code = app.main(["--json", "update"])
        self.assertEqual(code, 1)
        discover.assert_not_called()
        self.assertIn("requires macOS", json.loads(output.getvalue())["error"]["message"])

    def test_root_mutation_is_rejected_before_discovery(self):
        output = io.StringIO()
        with patch.object(app.sys, "platform", "darwin"), patch.object(app.os, "geteuid", return_value=0), patch.object(app, "discover") as discover, contextlib.redirect_stdout(output):
            code = app.main(["--json", "update"])
        self.assertEqual(code, 1)
        discover.assert_not_called()
        self.assertIn("normal user", json.loads(output.getvalue())["error"]["message"])

    def test_second_mutating_invocation_cannot_take_the_lock(self):
        with patch.object(app, "HOME_DIR", self.root), app.update_lock():
            with self.assertRaisesRegex(RuntimeError, "already running"):
                with app.update_lock():
                    self.fail("A second updater acquired the same lock")

    def test_download_rejects_https_downgrade(self):
        response = self.forti_response("7.4.3.4323")
        response.geturl.return_value = "http://filestore.fortinet.com/download.dmg"
        with patch.object(app.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "HTTPS"):
                app.download_file("https://filestore.fortinet.com/download.dmg", self.root / "file")
        self.assertFalse((self.root / "file").exists())

    def test_download_size_is_bounded(self):
        response = self.forti_response("7.4.3.4323")
        response.read.side_effect = [b"oversized response", b""]
        with patch.object(app.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "size limit"):
                app.download_file("https://filestore.fortinet.com/download.dmg", self.root / "file", max_bytes=3)
        self.assertEqual((self.root / "file").read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
