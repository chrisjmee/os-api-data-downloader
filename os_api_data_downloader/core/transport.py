"""HTTP transport.

Inside QGIS, requests go through ``QgsBlockingNetworkRequest`` so they use
QGIS's network settings (proxy, SSL exceptions, custom CA) - important on
locked-down public-sector networks where plain ``requests`` often fails.
It is safe to call from a ``QgsTask`` worker thread.

Outside QGIS (tests, command line) ``urllib`` is used.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


def _readable(status, body):
    """A short, readable reason - not a page of HTML."""
    text = (body or "").strip()
    if text.startswith("<"):
        import re as _re
        m = _re.search(r"<title>(.*?)</title>", text, _re.S | _re.I)
        text = (m.group(1).strip() if m else "") or "the server turned the request away"
        if status == 400:
            text += " - the request may be too long (e.g. a very detailed area plus many ticked values)"
    return text[:200]


class HttpError(Exception):
    def __init__(self, status, body="", url=""):
        super().__init__(f"HTTP {status} for {url.split('?')[0]}: {_readable(status, body)}")
        self.status = status
        self.body = body
        self.url = url


def _redact(url):
    parts = urllib.parse.urlsplit(url)
    q = [(k, "***" if k.lower() == "key" else v) for k, v in urllib.parse.parse_qsl(parts.query)]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))


def build_url(base, params):
    items = []
    for k, v in (params or {}).items():
        if v is None or v == "":
            continue
        if isinstance(v, (list, tuple)):
            items.extend((k, str(x)) for x in v)
        else:
            items.append((k, str(v)))
    return f"{base}?{urllib.parse.urlencode(items)}" if items else base


class UrllibTransport:
    timeout = 30

    def request(self, method, url, body=None, headers=None, retries=None):
        data = json.dumps(body).encode() if body is not None else None
        opener = getattr(self, "_opener", None)

        def send():
            req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
            if data is not None:
                req.add_header("Content-Type", "application/json")
            try:
                resp = opener.open(req, timeout=self.timeout) if opener else \
                    urllib.request.urlopen(req, timeout=self.timeout)
                with resp:
                    return resp.status, resp.read(), None
            except urllib.error.HTTPError as ex:
                return ex.code, ex.read(), ex.headers.get("Retry-After") if ex.headers else None
        return with_retries(send, url, notify=getattr(self, "notify", None), retries=retries)

    def _download_once(self, url, dest_path, progress=None, is_cancelled=None):
        with urllib.request.urlopen(url, timeout=self.timeout) as resp, open(dest_path, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if is_cancelled and is_cancelled():
                    raise RuntimeError("Download cancelled")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(100.0 * done / total)
        return dest_path


def _enum(cls, scope, name):
    """Scoped enum (PyQt6 / QGIS 4) with a fallback to the unscoped PyQt5 spelling."""
    scoped = getattr(cls, scope, None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)
    return getattr(cls, name)


class QgisTransport:
    """QgsBlockingNetworkRequest-based transport (respects QGIS proxy)."""

    def __init__(self, authcfg=None):
        self.authcfg = authcfg

    def notify(self, msg):
        from qgis.core import Qgis, QgsMessageLog
        QgsMessageLog.logMessage(msg, "OS Data Hub", Qgis.MessageLevel.Warning)

    def request(self, method, url, body=None, headers=None, retries=None):
        """``retries``: how many times to retry a busy server / dropped connection (default ``RETRIES``,
        with waits of up to a minute each) - optional lookups pass a small number to fail fast."""
        return with_retries(lambda: self._send(method, url, body, headers), url, notify=self.notify,
                            retries=retries)

    def _send(self, method, url, body=None, headers=None):
        from qgis.core import QgsBlockingNetworkRequest
        from qgis.PyQt.QtCore import QByteArray, QUrl
        from qgis.PyQt.QtNetwork import QNetworkRequest

        req = QNetworkRequest(QUrl(url))
        for k, v in (headers or {}).items():
            req.setRawHeader(k.encode(), v.encode())
        blocking = QgsBlockingNetworkRequest()
        if self.authcfg:
            blocking.setAuthCfg(self.authcfg)
        if method == "POST":
            req.setHeader(_enum(QNetworkRequest, "KnownHeaders", "ContentTypeHeader"), "application/json")
            err = blocking.post(req, QByteArray(json.dumps(body or {}).encode()))
        else:
            err = blocking.get(req, forceRefresh=True)
        reply = blocking.reply()
        status = reply.attribute(_enum(QNetworkRequest, "Attribute", "HttpStatusCodeAttribute"))
        if hasattr(status, "isNull"):  # QVariant on some builds
            status = None if status.isNull() else status.value()
        content = bytes(reply.content())
        if status is None:
            raise ConnectionError(f"Network error contacting {_redact(url).split('?')[0]}: "
                                  f"{blocking.errorMessage() or err}")
        retry_after = bytes(reply.rawHeader(b"Retry-After")).decode() if hasattr(reply, "rawHeader") else None
        return int(status), content, retry_after

    def _download_once(self, url, dest_path, progress=None, is_cancelled=None):
        # QgsBlockingNetworkRequest buffers in memory; OS Downloads files can be
        # several GB, so stream with urllib but honour the QGIS proxy settings.
        from qgis.core import QgsNetworkAccessManager
        proxy = QgsNetworkAccessManager.instance().fallbackProxy()
        handlers = []
        if proxy and proxy.hostName():
            p = f"http://{proxy.hostName()}:{proxy.port()}"
            handlers.append(urllib.request.ProxyHandler({"http": p, "https": p}))
        opener = urllib.request.build_opener(*handlers)
        with opener.open(url, timeout=60) as resp, open(dest_path, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if is_cancelled and is_cancelled():
                    raise RuntimeError("Download cancelled")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(100.0 * done / total)
        return dest_path


def default_transport():
    import importlib.util
    if importlib.util.find_spec("qgis") is not None:
        return QgisTransport()
    return UrllibTransport()


# ---------------------------------------------------------------- retries
# OS Data Hub answers 429 when a project goes over its rate limit, and gateways occasionally
# return 502/503/504; dropped connections and timeouts happen on long downloads. All of these
# are retried after a pause (2, 4, 8, 16, 32 s, then 60 s - or the server's Retry-After), so a
# big download slows down instead of failing. Transactions are counted once per request by the
# callers, not once per attempt.
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRIES = 6
BASE_DELAY = 2.0
MAX_DELAY = 60.0


def _delay(attempt, retry_after=None):
    try:
        if retry_after:
            return min(MAX_DELAY, max(1.0, float(retry_after)))
    except (TypeError, ValueError):
        pass
    return min(MAX_DELAY, BASE_DELAY * 2 ** attempt)


def with_retries(send, url, sleep=None, notify=None, retries=None):
    """``send()`` -> (status, content, retry_after). Returns (status, content)."""
    import time as _time
    sleep = sleep or _time.sleep
    retries = RETRIES if retries is None else retries
    attempt = 0
    while True:
        try:
            status, content, retry_after = send()
        except (OSError, ConnectionError, TimeoutError) as ex:   # includes urllib's URLError and socket errors
            if attempt >= retries:
                raise
            wait = _delay(attempt)
            if notify:
                notify(f"Network problem ({ex}); retrying in {wait:.0f} s ({attempt + 1}/{retries})")
        else:
            if status not in RETRY_STATUS or attempt >= retries:
                return status, content
            wait = _delay(attempt, retry_after)
            if notify:
                why = "rate limit reached" if status == 429 else f"server busy (HTTP {status})"
                notify(f"OS Data Hub {why} - waiting {wait:.0f} s, then trying again ({attempt + 1}/{retries})")
        sleep(wait)
        attempt += 1


def _retrying_download(once):
    def download(self, url, dest_path, progress=None, is_cancelled=None):
        """Large files: a dropped connection or timeout starts the file again (up to 3 tries)."""
        attempt = 0
        while True:
            try:
                return once(self, url, dest_path, progress, is_cancelled)
            except (OSError, ConnectionError, TimeoutError) as ex:
                if attempt >= 2 or (is_cancelled and is_cancelled()):
                    raise
                note = getattr(self, "notify", None)
                if note:
                    note(f"Download interrupted ({ex}); starting it again ({attempt + 1}/2)")
                import time as _time
                _time.sleep(_delay(attempt + 1))
                attempt += 1
    return download


UrllibTransport.download = _retrying_download(UrllibTransport._download_once)
QgisTransport.download = _retrying_download(QgisTransport._download_once)
