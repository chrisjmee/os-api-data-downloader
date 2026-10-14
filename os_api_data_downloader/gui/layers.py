"""Coordinate helpers (everything is requested and stored in British National Grid)."""

from __future__ import annotations

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProject

BNG = QgsCoordinateReferenceSystem("EPSG:27700")


def canvas_extent_bng(canvas):
    tr = QgsCoordinateTransform(canvas.mapSettings().destinationCrs(), BNG, QgsProject.instance())
    return tr.transformBoundingBox(canvas.extent())


def geometry_to_bng(geom, crs):
    g = QgsGeometry(geom)
    if crs != BNG:
        g.transform(QgsCoordinateTransform(crs, BNG, QgsProject.instance()))
    return g
