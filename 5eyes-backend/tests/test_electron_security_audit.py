"""Sprint U-61 (Roadmap-Punkt 61, 2026-06-01): Electron Security Audit.

Pure Source-Parsing-Tests gegen main.js + preload.js — keine Node-Runtime
noetig. Schlaegt fehl, wenn jemand die Hardening-Settings versehentlich
abdreht (typischer Drift bei electron-Upgrade oder Refactor).

Audit-Quelle (Stand 2026-06-01)
-------------------------------
Electron Hardening Checklist (https://www.electronjs.org/docs/latest/tutorial/security)
- contextIsolation: true
- nodeIntegration: false
- sandbox: true
- webSecurity: true (explizit)
- allowRunningInsecureContent: false (explizit)
- experimentalFeatures: false (explizit)
- devTools: nur in dev
- preload nutzt contextBridge (kein window.x = ...)
- preload exportiert KEIN raw ipcRenderer
- setPermissionRequestHandler default-deny
- web-contents-created globaler Hook
- will-attach-webview blockiert
- setWindowOpenHandler action:deny

FINMA-Bezug
-----------
Berater-App haelt Bearer-Token + DSG-relevante Mandantendaten. Ein
kompromittiertes Renderer-Prozess waere DSGV/FINMA-Incident.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_JS = REPO_ROOT / "5eyes-electron" / "main.js"
PRELOAD_JS = REPO_ROOT / "5eyes-electron" / "preload.js"


@pytest.fixture(scope="module")
def main_source() -> str:
    assert MAIN_JS.exists(), f"main.js fehlt: {MAIN_JS}"
    return MAIN_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def preload_source() -> str:
    assert PRELOAD_JS.exists(), f"preload.js fehlt: {PRELOAD_JS}"
    return PRELOAD_JS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# webPreferences Hardening (BrowserWindow)
# ---------------------------------------------------------------------------

def test_context_isolation_enabled(main_source):
    assert "contextIsolation: true" in main_source, (
        "contextIsolation MUSS true sein — sonst kann Renderer-Code "
        "in Main-Prozess eingreifen."
    )


def test_node_integration_disabled(main_source):
    assert "nodeIntegration: false" in main_source, (
        "nodeIntegration MUSS false sein — sonst hat Renderer Zugriff "
        "auf fs/child_process/etc."
    )


def test_sandbox_enabled(main_source):
    assert "sandbox: true" in main_source, (
        "sandbox MUSS true sein — Chromium-OS-Sandbox aktiv."
    )


def test_web_security_explicit(main_source):
    """U-61: webSecurity ist default true, aber FINMA-Audit verlangt
    explizite Konfiguration (kein implizites Vertrauen auf Defaults)."""
    assert "webSecurity: true" in main_source, (
        "webSecurity MUSS explizit true sein (FINMA-Audit-Spur)."
    )


def test_allow_insecure_content_explicit_false(main_source):
    assert "allowRunningInsecureContent: false" in main_source, (
        "allowRunningInsecureContent MUSS explizit false sein."
    )


def test_experimental_features_disabled(main_source):
    assert "experimentalFeatures: false" in main_source, (
        "experimentalFeatures MUSS false sein — keine instabilen "
        "Chromium-Flags."
    )


def test_devtools_only_in_dev(main_source):
    assert "devTools: !app.isPackaged" in main_source, (
        "devTools MUSS in production-Build aus sein (verhindert "
        "Token-Extraktion via Renderer-Inspector)."
    )


# ---------------------------------------------------------------------------
# Globale web-contents-created Hardening
# ---------------------------------------------------------------------------

def test_web_contents_created_hook_exists(main_source):
    assert "app.on('web-contents-created'" in main_source, (
        "Globaler web-contents-created-Hook fehlt — neue Renderer "
        "(Sub-Windows, devTools etc.) waeren ungeschuetzt."
    )


def test_permission_request_handler_denies(main_source):
    assert "setPermissionRequestHandler" in main_source, (
        "Default-deny-PermissionRequestHandler fehlt — Browser-APIs "
        "wie geolocation/notifications/mediaDevices waeren erlaubt."
    )
    # Sicherstellen dass es ein deny ist (callback(false))
    idx = main_source.find("setPermissionRequestHandler")
    snippet = main_source[idx:idx + 300]
    assert "callback(false)" in snippet, (
        "setPermissionRequestHandler ruft kein callback(false) — "
        "evtl. accidental-allow."
    )


def test_will_attach_webview_blocked(main_source):
    assert "will-attach-webview" in main_source, (
        "will-attach-webview Hook fehlt — embedded <webview> Tags "
        "koennten Sicherheits-Settings umgehen."
    )
    idx = main_source.find("will-attach-webview")
    snippet = main_source[idx:idx + 400]
    assert "event.preventDefault" in snippet, (
        "will-attach-webview muss preventDefault aufrufen."
    )


def _function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    return source[start:source.index("\n}\n", start)]


def test_window_open_handler_denies(main_source):
    """ELECTRON-NAV-URL-001: genau ein globaler Handler (gilt fuer jedes
    WebContents, auch das Hauptfenster); er oeffnet nie ein neues Fenster."""
    assert main_source.count("setWindowOpenHandler(") == 1
    assert "contents.setWindowOpenHandler(handleWindowOpen)" in main_source
    body = _function_body(main_source, "function handleWindowOpen(")
    assert "return { action: 'deny' };" in body
    assert "action: 'allow'" not in main_source


def test_will_navigate_blocks_external(main_source):
    """ELECTRON-NAV-URL-001: will-navigate und will-redirect laufen ueber
    dieselbe Pruefung wie die IPC-Absender; kein zweiter window-lokaler Hook
    (der externe Links doppelt oeffnen wuerde) und kein String-Vergleich."""
    assert main_source.count("on('will-navigate'") == 1
    assert "contents.on('will-navigate', guardNavigation)" in main_source
    assert "contents.on('will-redirect', guardNavigation)" in main_source
    body = _function_body(main_source, "function guardNavigation(")
    assert "isLocalEntryUrl(url)" in body
    assert body.index("isLocalEntryUrl(url)") < body.index("event.preventDefault()")
    entry_check = _function_body(main_source, "function isLocalEntryUrl(")
    assert "checkTrustedRendererUrl(url, resolveFrontendPath())" in entry_check
    assert "localEntry" not in main_source


# ---------------------------------------------------------------------------
# isSafeExternalUrl — keine Duplikate (U-61 Code-Smell-Fix)
# ---------------------------------------------------------------------------

def test_is_safe_external_url_defined_once(main_source):
    """Pre-U-61 war die Funktion DOPPELT definiert (Z.9 + Z.66) — die
    zweite ueberschrieb die erste. Drift-Schutz."""
    count = main_source.count("function isSafeExternalUrl(")
    assert count == 1, (
        f"isSafeExternalUrl MUSS genau 1x definiert sein, gefunden: "
        f"{count}. Wenn >1: zweite ueberschreibt erste -> Bug-Quelle."
    )


def test_is_safe_external_url_blocks_arbitrary_protocols(main_source):
    """Die Funktion darf nur https:// und http://localhost|127.0.0.1
    durchlassen — keine file://, javascript:, data:, etc."""
    idx = main_source.find("function isSafeExternalUrl(")
    end = main_source.find("\n}\n", idx)
    fn = main_source[idx:end + 3]
    assert "'https:'" in fn
    assert "'http:'" in fn
    assert "localhost" in fn
    assert "127.0.0.1" in fn


# ---------------------------------------------------------------------------
# preload.js — contextBridge-Only, kein raw ipcRenderer
# ---------------------------------------------------------------------------

def test_preload_uses_context_bridge(preload_source):
    assert "contextBridge.exposeInMainWorld" in preload_source, (
        "preload muss contextBridge nutzen (kein window.X = ...)."
    )


def test_preload_does_not_expose_raw_ipc_renderer(preload_source):
    """Kein direkter ipcRenderer-Export — sonst koennte Renderer
    beliebige IPC-Channels triggern."""
    assert "exposeInMainWorld('ipcRenderer'" not in preload_source
    assert "exposeInMainWorld(\"ipcRenderer\"" not in preload_source
    # Auch kein generisches send/invoke ohne Channel-Whitelist
    assert "ipcRenderer.send" not in preload_source, (
        "preload exportiert raw ipcRenderer.send — Renderer kann "
        "beliebige Channels triggern."
    )


def test_preload_only_requires_electron(preload_source):
    """preload soll nur 'electron' requiren — keine fs/path/child_process."""
    forbidden = ["require('fs')", "require('path')", "require('child_process')",
                 "require('os')", "require('http')"]
    for mod in forbidden:
        assert mod not in preload_source, (
            f"preload requires {mod} — Renderer-Surface vergroessert."
        )


# ---------------------------------------------------------------------------
# Single-Instance + Token-Storage
# ---------------------------------------------------------------------------

def test_single_instance_lock(main_source):
    """Mehrere App-Instanzen wuerden DB-Lock-Konflikte triggern."""
    assert "requestSingleInstanceLock" in main_source


def test_token_storage_uses_safe_storage(main_source):
    """Token darf nicht als Klartext auf Disk landen — safeStorage
    (OS-Keychain) Pflicht."""
    assert "safeStorage.isEncryptionAvailable" in main_source
    assert "safeStorage.encryptString" in main_source
    assert "safeStorage.decryptString" in main_source


# ---------------------------------------------------------------------------
# A3 P2-5 / U-6: IPC-Absender-Pruefung fuer jeden Kanal
# ---------------------------------------------------------------------------

ELECTRON_DIR = MAIN_JS.parent
IPC_GUARD_JS = ELECTRON_DIR / "ipc-sender-guard.js"
IPC_GUARD_TEST_JS = ELECTRON_DIR / "tests" / "ipc-sender-guard.test.js"


def test_every_ipc_handler_goes_through_sender_guard(main_source):
    """Genau EIN direkter ipcMain.handle-Aufruf: der im zentralen Wrapper.
    Jeder Kanal muss ueber handleTrustedIpc registriert werden."""
    assert main_source.count("ipcMain.handle(") == 1, (
        "ipcMain.handle direkt aufgerufen -- Kanal umgeht die Absender-Pruefung."
    )
    assert "ipcMain.on(" not in main_source
    assert "checkTrustedIpcSender(event, resolveFrontendPath())" in main_source
    assert main_source.count("handleTrustedIpc('") >= 15


def test_push_channel_checks_renderer_url(main_source):
    start = main_source.index("function notifyRendererUpdateState()")
    body = main_source[start:main_source.index("\n}\n", start)]
    assert "checkTrustedRendererUrl(" in body
    assert body.index("checkTrustedRendererUrl(") < body.index(".send(")


def test_ipc_guard_module_is_packaged():
    """Ohne Eintrag in build.files fehlt das Modul in der gepackten App und
    main.js bricht beim Start ab."""
    import json

    pkg = json.loads((ELECTRON_DIR / "package.json").read_text(encoding="utf-8"))
    assert IPC_GUARD_JS.exists()
    assert "ipc-sender-guard.js" in pkg["build"]["files"]


def test_ipc_sender_guard_node_suite():
    """Fuehrt die node:test-Suite (Validierung + Verdrahtung) aus."""
    import shutil
    import subprocess

    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    res = subprocess.run(
        ["node", "--test", str(IPC_GUARD_TEST_JS)],
        cwd=str(ELECTRON_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert res.returncode == 0, res.stdout[-4000:] + res.stderr[-2000:]
