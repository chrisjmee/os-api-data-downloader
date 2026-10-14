# Tests

Offline tests of the NGD Data Linkages tab against a fake OS API (no API key or network needed).
They need QGIS's Python (3.28+), e.g. on Windows the OSGeo4W Shell, then from the repository root:

    set QT_QPA_PLATFORM=offscreen
    python-qgis tests\test_links.py
    python-qgis tests\test_answer.py

Each prints `... OK` at the end when it passes.
