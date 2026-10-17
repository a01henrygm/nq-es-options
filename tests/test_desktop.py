"""Desktop app pieces that run anywhere: the self-updater (against a FAKE GitHub served by httpx.MockTransport), version
handling, the data folder, the Mac update and login item, and the release build files. The window and tray themselves only run
on Windows and Mac (the Mac build starts the real app once with --smoke-test)."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from desktop import updater as up

ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")
BLOB = b"MZ" + b"x" * 5000


def fake_github(tag="v1.3.0", private=False, assets=None, status=200, seen=None):
    seen = seen if seen is not None else []
    assets = assets if assets is not None else [
        {"name": "notes.txt", "url": "https://api.github.com/repos/o/r/releases/assets/1", "browser_download_url": "https://github.com/o/r/releases/download/x/notes.txt", "size": 3},
        {"name": f"NQ-ES-Options-{tag[1:]}-Setup.exe", "url": "https://api.github.com/repos/o/r/releases/assets/2",
         "browser_download_url": f"https://github.com/o/r/releases/download/{tag}/NQ-ES-Options-{tag[1:]}-Setup.exe", "size": len(BLOB)}]

    def handler(req: httpx.Request):
        seen.append(req)
        if private and req.url.host in ("api.github.com",) and req.headers.get("Authorization") != "Bearer tok":
            return httpx.Response(404, json={"message": "Not Found"})
        if req.url.path == "/repos/o/r/releases/latest":
            return httpx.Response(status, json={"tag_name": tag, "body": "Faster levels", "assets": assets})
        if req.url.path == "/repos/o/r/releases/assets/2":
            assert req.headers["Accept"] == "application/octet-stream"
            return httpx.Response(302, headers={"Location": "https://objects.githubusercontent.com/blob"})
        if req.url.host == "objects.githubusercontent.com":
            assert "Authorization" not in req.headers                        # the token is not sent on to the file host
            return httpx.Response(200, content=BLOB)
        if req.url.host == "github.com" and req.url.path.endswith("-Setup.exe"):
            return httpx.Response(200, content=BLOB)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True), seen


def test_versions_compare_as_numbers():
    assert up.parse_version("v1.10.0") == (1, 10, 0) and up.parse_version("2") == (2, 0, 0) and up.parse_version("junk") == (0, 0, 0)
    assert up.is_newer("v1.10.0", "1.9.9") and not up.is_newer("1.0.0", "1.0.0") and not up.is_newer("v0.9", "1.0.0")


def test_latest_release_picks_the_installer_and_handles_no_release():
    c, _ = fake_github()
    r = up.latest_release("o/r", client=c)
    assert r["version"] == "1.3.0" and r["name"] == "NQ-ES-Options-1.3.0-Setup.exe" and r["size"] == len(BLOB) and r["notes"] == "Faster levels"
    c, _ = fake_github(assets=[])
    assert up.latest_release("o/r", client=c) is None                                     # a release without an installer is ignored
    c, _ = fake_github(status=404)
    assert up.latest_release("o/r", client=c) is None


def test_download_public_and_private(tmp_path):
    c, seen = fake_github()
    p = up.download(up.latest_release("o/r", client=c), tmp_path / "pub", client=c)
    assert p.read_bytes() == BLOB and seen[-1].url.host == "github.com"
    c, seen = fake_github(private=True)
    assert up.latest_release("o/r", client=c) is None                                     # private repo, no token: looks like no release
    rel = up.latest_release("o/r", token="tok", client=c)
    p = up.download(rel, tmp_path / "priv", token="tok", client=c)
    assert p.read_bytes() == BLOB and any(r.url.host == "objects.githubusercontent.com" for r in seen)
    assert up.download(rel, tmp_path / "priv", token="tok", client=c) == p                # already there: not downloaded again


def test_download_rejects_a_short_file(tmp_path):
    c, _ = fake_github()
    rel = {**up.latest_release("o/r", client=c), "size": len(BLOB) + 10}
    with pytest.raises(IOError):
        up.download(rel, tmp_path, client=c)
    assert not (tmp_path / rel["name"]).exists()


def test_updater_states(tmp_path):
    seen_states = []
    c, _ = fake_github(tag="v1.3.0")
    u = up.Updater("1.2.0", "o/r", folder=tmp_path, on_change=lambda x: seen_states.append(x.state))
    assert u.check(client=c) == "ready" and u.path.read_bytes() == BLOB and u.info()["latest"] == "1.3.0"
    assert "downloading" in seen_states
    assert up.Updater("1.3.0", "o/r", folder=tmp_path).check(client=c) == "up_to_date"
    assert up.Updater("1.2.0", "o/r", auto=False, folder=tmp_path).check(client=c) == "available"
    assert up.Updater("1.2.0", "", folder=tmp_path).check(client=c) == "off"
    bad, _ = fake_github(status=500)
    u = up.Updater("1.2.0", "o/r", folder=tmp_path)
    assert u.check(client=bad) == "error" and u.info()["error"]


def test_install_runs_the_installer_silently(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(up.subprocess, "Popen", lambda args, **kw: calls.append(args))
    c, _ = fake_github()
    u = up.Updater("1.0.0", "o/r", folder=tmp_path)
    assert not u.install()                                                                # nothing downloaded yet
    u.check(client=c)
    assert u.install() and calls[0][0].endswith("-Setup.exe") and "/VERYSILENT" in calls[0] and "/SUPPRESSMSGBOXES" in calls[0]


def test_update_settings_from_env():
    s = up.settings_from_env({"UPDATE_REPO": " me/app ", "UPDATE_TOKEN": "", "AUTO_UPDATE": "0"})
    assert s == {"repo": "me/app", "token": None, "auto": False}
    assert up.settings_from_env({})["auto"] is True


def test_no_self_restart_during_market_hours():
    from desktop.app import _market_hours
    assert _market_hours(datetime(2026, 10, 16, 10, 0, tzinfo=ET))                       # Friday 10:00
    assert not _market_hours(datetime(2026, 10, 16, 17, 0, tzinfo=ET))                   # after the close
    assert not _market_hours(datetime(2026, 10, 17, 10, 0, tzinfo=ET))                   # Saturday


def test_data_folder_is_the_project_folder_when_run_from_source(tmp_path, monkeypatch):
    from backend import config
    assert not config.FROZEN and config.DATA == config.ROOT
    monkeypatch.setattr(config, "DATA", tmp_path / "appdata")
    config.ensure_data_dir()
    assert (tmp_path / "appdata" / ".env").read_text() == (ROOT / ".env.example").read_text()
    assert (tmp_path / "appdata" / "data").is_dir() and (tmp_path / "appdata" / "logs").is_dir()


def test_release_build_files_fit_together():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    iss = (ROOT / "installer" / "setup.iss").read_text()
    spec = (ROOT / "installer" / "build.ps1").read_text()
    assert "branches: [main]" in wf and "gh release view" in wf and "tag_name: v" in wf and "windows-latest" in wf and "pytest" in wf and "build.ps1" in wf
    assert "PrivilegesRequired=lowest" in iss and "{localappdata}" in iss.lower() or "{userpf}" in iss.lower()
    assert "NQ-ES-Options-{#MyVersion}-Setup" in iss and "postinstall" in iss and "CloseApplications" in iss
    assert "--add-data" in spec and "frontend" in spec and "NQES.py" in spec and "assets" in spec
    assert (ROOT / "assets" / "icon.ico").exists() and (ROOT / "requirements-desktop.txt").exists()


# ---- Mac -------------------------------------------------------------------------------------------------------------
def _mac_assets(tag="v1.4.0"):
    v = tag[1:]
    names = [f"NQ-ES-Options-{v}-Setup.exe", f"Q-DATA-{v}-macOS-arm64.dmg", f"Q-DATA-{v}-macOS-arm64.zip",
             f"Q-DATA-{v}-macOS-x86_64.dmg", f"Q-DATA-{v}-macOS-x86_64.zip"]
    return [{"name": n, "url": f"https://api.github.com/repos/o/r/releases/assets/{i}", "browser_download_url": f"https://github.com/o/r/releases/download/{tag}/{n}",
             "size": 10} for i, n in enumerate(names, 10)]


def test_each_computer_picks_its_own_release_file():
    c, _ = fake_github(tag="v1.4.0", assets=_mac_assets())
    assert up.latest_release("o/r", client=c, pattern=up.asset_pattern("win32"))["name"].endswith("-Setup.exe")
    assert up.latest_release("o/r", client=c, pattern=up.asset_pattern("darwin", "arm64"))["name"] == "Q-DATA-1.4.0-macOS-arm64.zip"
    assert up.latest_release("o/r", client=c, pattern=up.asset_pattern("darwin", "x86_64"))["name"] == "Q-DATA-1.4.0-macOS-x86_64.zip"
    only_windows = [a for a in _mac_assets() if a["name"].endswith(".exe")]
    c, _ = fake_github(tag="v1.4.0", assets=only_windows)
    assert up.latest_release("o/r", client=c, pattern=up.asset_pattern("darwin", "arm64")) is None    # no Mac build in it: stay put


def test_mac_finds_its_app_and_refuses_to_update_from_a_bad_place(tmp_path):
    exe = tmp_path / "Applications" / "Q DATA.app" / "Contents" / "MacOS" / "Q DATA"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    bundle = up.mac_app_bundle(str(exe))
    assert bundle.name == "Q DATA.app" and up.mac_update_problem(bundle) is None
    assert up.mac_app_bundle(str(tmp_path / "python3")) is None and up.mac_update_problem(None)
    assert "Applications" in up.mac_update_problem(Path("/private/var/folders/x/AppTranslocation/ABC/d/Q DATA.app"))
    assert "Applications" in up.mac_update_problem(Path("/Volumes/Q DATA/Q DATA.app"))


def test_mac_update_unpacks_and_hands_over_to_the_swap_script(tmp_path, monkeypatch):
    import zipfile
    bundle = tmp_path / "Applications" / "Q DATA.app"
    (bundle / "Contents").mkdir(parents=True)
    work = tmp_path / "updates"
    work.mkdir()
    z = work / "Q-DATA-1.4.0-macOS-arm64.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Q DATA.app/Contents/Info.plist", "<plist/>")
    calls = []
    monkeypatch.setattr(up.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    up.run_mac_update(z, background=True, bundle=bundle, unzip=lambda zp, out: zipfile.ZipFile(zp).extractall(out))
    args, kw = calls[0]
    assert args[0] == "/bin/sh" and args[1].endswith("swap.sh") and args[3].endswith("staged/Q DATA.app") and args[4] == str(bundle)
    assert args[-1] == "--background" and kw["start_new_session"]
    assert (work / "staged" / "Q DATA.app" / "Contents" / "Info.plist").exists()
    script = (work / "swap.sh").read_text()
    assert 'kill -0 "$pid"' in script and 'mv "$new" "$dest"' in script and 'open "$dest"' in script and "quarantine" in script
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("readme.txt", "x")
    with pytest.raises(IOError):
        up.run_mac_update(z, bundle=bundle, unzip=lambda zp, out: zipfile.ZipFile(zp).extractall(out))


def test_a_failed_install_is_reported_not_raised(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Move Q DATA into your Applications folder")
    monkeypatch.setattr(up, "run_installer", boom)
    c, _ = fake_github()
    u = up.Updater("1.0.0", "o/r", folder=tmp_path)
    u.check(client=c)
    assert u.install() is False and u.state == "error" and "Applications" in u.info()["error"]


def test_mac_login_item_and_settings_folder(tmp_path):
    import plistlib
    from desktop import autostart
    from backend.config import installed_data_dir
    d = plistlib.loads(autostart.mac_plist("/Applications/Q DATA.app/Contents/MacOS/Q DATA"))
    assert d["Label"] == "com.qdata.app" and d["RunAtLoad"] is True
    assert d["ProgramArguments"] == ["/Applications/Q DATA.app/Contents/MacOS/Q DATA", "--background"]
    assert autostart.mac_plist_path(tmp_path) == tmp_path / "Library" / "LaunchAgents" / "com.qdata.app.plist"
    assert installed_data_dir("darwin", {}, tmp_path) == tmp_path / "Library" / "Application Support" / "Q DATA"
    assert installed_data_dir("win32", {"LOCALAPPDATA": str(tmp_path)}, tmp_path) == tmp_path / "NQ-ES Options"


def test_mac_release_build_fits_together():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    sh = (ROOT / "installer" / "build_mac.sh").read_text()
    assert "build_mac.sh" in wf and "macos-latest" in wf and "--smoke-test" in wf and "out/*.dmg" in wf and "out/*.zip" in wf
    assert "needs.build.result == 'success'" in wf                       # a Mac build failing never holds back the Windows update
    assert 'NAME="Q-DATA-${VERSION}-macOS-${ARCH}"' in sh and "ditto -c -k" in sh and "hdiutil create" in sh
    assert "webview.platforms.cocoa" in sh and "pystray._darwin" in sh and "frontend:frontend" in sh and "codesign" in sh
    assert up.asset_pattern("darwin", "arm64").search("Q-DATA-1.4.0-macOS-arm64.zip")         # the names the build makes are the names the app looks for
    assert up.ASSET_RE.search("NQ-ES-Options-1.4.0-Setup.exe")


def test_single_copy_lock_off_windows(tmp_path, monkeypatch):
    import sys as _sys
    if _sys.platform == "win32":
        pytest.skip("Windows uses a mutex")
    from desktop import app as dapp
    monkeypatch.setattr(dapp, "DATA", tmp_path)
    first = dapp._single_instance()
    assert first is not None
    import subprocess, textwrap
    code = textwrap.dedent(f"""
        import fcntl, sys
        f = open({str(tmp_path / 'desktop.lock')!r}, 'a+')
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); print('got')
        except OSError:
            print('busy')
    """)
    assert subprocess.run([_sys.executable, "-c", code], capture_output=True, text=True).stdout.strip() == "busy"
    first.close()
