def classFactory(iface):  # noqa: N802 - QGIS entry point
    from .plugin import OsApiDataDownloaderPlugin
    return OsApiDataDownloaderPlugin(iface)
