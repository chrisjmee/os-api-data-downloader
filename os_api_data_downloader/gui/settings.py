"""Plugin settings (QgsSettings) and API key storage (QGIS Authentication
Database - encrypted, never written to plugin files or the project)."""

from __future__ import annotations

import os

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

PREFIX = "os_data_loader/"   # kept from the plugin's first name, so saved settings and the API key carry over
AUTH_NAME = "OS API Data Downloader - OS Data Hub API key"
ENV_VARS = ("OS_API_KEY", "OS_PLACES_API_KEY")

DEFAULTS = {
    "confirm_over": 1000,
    "hard_limit": 0,
    "folder": "",
    "clip_mode": "clip",
}

_BOOL_KEYS = {k for k, v in DEFAULTS.items() if isinstance(v, bool)}
_INT_KEYS = {k for k, v in DEFAULTS.items() if isinstance(v, int) and not isinstance(v, bool)}


def get(key):
    s = QgsSettings()
    default = DEFAULTS.get(key)
    if key in _BOOL_KEYS:
        return s.value(PREFIX + key, default, type=bool)
    if key in _INT_KEYS:
        try:
            return int(s.value(PREFIX + key, default))
        except (TypeError, ValueError):
            return default
    v = s.value(PREFIX + key, default)
    return "" if v is None else str(v)


def set_(key, value):
    QgsSettings().setValue(PREFIX + key, value)


def output_folder():
    return get("folder") or os.path.join(os.path.expanduser("~"), "OS data")


# ---------------------------------------------------------------- API key
def _auth_id():
    return QgsSettings().value(PREFIX + "auth/config_id", "") or ""


def load_api_key():
    """Key from the QGIS auth DB; falls back to the OS_API_KEY / OS_PLACES_API_KEY environment variables."""
    cfg_id = _auth_id()
    if cfg_id:
        am = QgsApplication.authManager()
        cfg = QgsAuthMethodConfig()
        if am.loadAuthenticationConfig(cfg_id, cfg, True):
            key = cfg.config("password", "")
            if key:
                return key
    return next((os.environ[v] for v in ENV_VARS if os.environ.get(v)), "")


def api_key_source():
    if _auth_id() and load_api_key():
        return "QGIS authentication database"
    for v in ENV_VARS:
        if os.environ.get(v):
            return f"{v} environment variable"
    return ""


def save_api_key(key):
    am = QgsApplication.authManager()
    if am.isDisabled():
        raise RuntimeError("The QGIS authentication system is disabled: " + am.disabledMessage())
    if not am.setMasterPassword(True):
        raise RuntimeError("The QGIS authentication database master password was not set or unlocked.")
    cfg = QgsAuthMethodConfig()
    cfg_id = _auth_id()
    if cfg_id and am.loadAuthenticationConfig(cfg_id, cfg, True):
        cfg.setConfig("password", key)
        ok = am.updateAuthenticationConfig(cfg)
    else:
        cfg = QgsAuthMethodConfig("Basic")
        cfg.setName(AUTH_NAME)
        cfg.setConfig("username", "os-data-hub")
        cfg.setConfig("password", key)
        res = am.storeAuthenticationConfig(cfg)
        if isinstance(res, tuple):  # PyQGIS returns (ok, config) for the in/out parameter
            ok, cfg = res
        else:
            ok = bool(res)
        if ok and cfg.id():
            QgsSettings().setValue(PREFIX + "auth/config_id", cfg.id())
    if not ok:
        raise RuntimeError("Could not store the API key in the QGIS authentication database.")


def clear_api_key():
    cfg_id = _auth_id()
    if cfg_id:
        QgsApplication.authManager().removeAuthenticationConfig(cfg_id)
    QgsSettings().remove(PREFIX + "auth/config_id")
