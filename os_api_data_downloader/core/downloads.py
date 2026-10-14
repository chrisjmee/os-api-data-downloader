"""OS Downloads API: OpenData products (no key) and premium data packages
(key required, e.g. a PSGA member's AddressBase / NGD orders).

OpenData products that are supplied in tiles use the two-letter 100 km
National Grid square as their ``area`` (e.g. "SD"), so the plugin works out
which squares an area of interest touches and downloads only those.
"""

from __future__ import annotations

import json
import math
import os

from .transport import HttpError, build_url, default_transport

DOWNLOADS_BASE = "https://api.os.uk/downloads/v1"

# Products most useful alongside address work - shown first in the UI.
FEATURED_OPEN_PRODUCTS = ["OpenZoomstack", "OpenMapLocal", "OpenRoads", "OpenRivers", "BoundaryLine", "Terrain50",
                          "OpenGreenspace", "OpenBuilt", "OpenNames", "OpenUPRN", "OpenUSRN", "OpenTOID",
                          "CodePointOpen"]


def bng_100km_square(e, n):
    """'SD' etc. for an Easting/Northing in EPSG:27700 (None if off-grid)."""
    if e < 0 or n < 0 or e >= 700000 or n >= 1300000:
        return None
    e100k, n100k = int(e // 100000), int(n // 100000)
    l1 = (19 - n100k) - (19 - n100k) % 5 + (e100k + 10) // 5
    l2 = (19 - n100k) * 5 % 25 + e100k % 5
    if l1 > 7:
        l1 += 1
    if l2 > 7:
        l2 += 1
    return chr(l1 + 65) + chr(l2 + 65)


def squares_for_extent(xmin, ymin, xmax, ymax, intersects=None):
    out = []
    for ex in range(int(math.floor(max(0, xmin) / 1e5)), int(math.floor(min(699999, xmax) / 1e5)) + 1):
        for ny in range(int(math.floor(max(0, ymin) / 1e5)), int(math.floor(min(1299999, ymax) / 1e5)) + 1):
            cell = (ex * 1e5, ny * 1e5, ex * 1e5 + 1e5, ny * 1e5 + 1e5)
            if intersects and not intersects(cell):
                continue
            sq = bng_100km_square(ex * 1e5 + 1, ny * 1e5 + 1)
            if sq and sq not in out:
                out.append(sq)
    return out


def human_size(n):
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class DownloadsClient:
    def __init__(self, api_key=None, transport=None, base=DOWNLOADS_BASE):
        self.api_key = api_key
        self.transport = transport or default_transport()
        self.base = base

    def _get(self, path, params=None, keyed=False):
        params = dict(params or {})
        if keyed:
            if not self.api_key:
                raise ValueError("Data packages need an OS Data Hub API key with the OS Downloads API enabled.")
            params["key"] = self.api_key
        url = build_url(f"{self.base}{path}", params)
        status, content = self.transport.request("GET", url)
        text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        if status != 200:
            raise HttpError(status, text, url)
        return json.loads(text)

    # OpenData
    def products(self):
        items = self._get("/products")
        featured = {p: i for i, p in enumerate(FEATURED_OPEN_PRODUCTS)}
        return sorted(items, key=lambda p: (featured.get(p.get("id"), 999), p.get("name") or p.get("id")))

    def product_downloads(self, product_id, area=None, fmt=None):
        return self._get(f"/products/{product_id}/downloads", {"area": area, "format": fmt})

    # Premium data packages
    def data_packages(self):
        return self._get("/dataPackages", keyed=True)

    def data_package_version(self, package_id, version_id):
        return self._get(f"/dataPackages/{package_id}/versions/{version_id}", keyed=True)

    def download(self, url, dest_dir, file_name=None, keyed=False, progress=None, is_cancelled=None):
        if keyed and self.api_key and "key=" not in url:
            url += ("&" if "?" in url else "?") + "key=" + self.api_key
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, file_name or url.split("?")[0].rsplit("/", 1)[-1])
        part = dest + ".part"
        self.transport.download(url, part, progress=progress, is_cancelled=is_cancelled)
        os.replace(part, dest)
        return dest
