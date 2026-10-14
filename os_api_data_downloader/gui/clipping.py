"""Clip downloaded data (and API features) to an area of interest.

Safe to run inside a QgsTask: layers are opened privately (never added to the
project) and written with GDAL / QgsVectorFileWriter.

Modes:
  "intersects" - keep whole features that touch the area (no geometry edits)
  "clip"       - cut features at the area's boundary

Downloaded files are clipped by ``clip_downloads``, which is built for speed on
big downloads:
  * ZIP files are unpacked to a temporary folder first. Reading a GeoPackage
    straight out of a ZIP means every spatial-index lookup decompresses part
    of the archive again, which is very slow.
  * The work is done inside GDAL (C++): the area's bounding box is used as a
    spatial filter (so a GeoPackage's spatial index skips everything far
    away), features are tested against the exact shape by GDAL, and in "cut"
    mode GDAL cuts them too (ogr2ogr -clipsrc). Python never touches the
    features that are thrown away.
  * Tiles of the same product are merged: one output layer per theme, not one
    per tile.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCoordinateTransformContext, QgsFeature,
    QgsFeatureRequest, QgsGeometry, QgsProviderRegistry, QgsRasterLayer, QgsVectorFileWriter, QgsVectorLayer,
    QgsWkbTypes,
)

BNG = QgsCoordinateReferenceSystem("EPSG:27700")

try:  # QGIS >= 3.30
    from qgis.core import Qgis
    _VECTOR_LAYER = Qgis.LayerType.Vector
    _POINT = Qgis.GeometryType.Point
except AttributeError:  # pragma: no cover
    from qgis.core import QgsMapLayerType
    _VECTOR_LAYER = QgsMapLayerType.VectorLayer
    _POINT = QgsWkbTypes.PointGeometry
RASTER_EXT = (".tif", ".tiff", ".asc", ".img", ".vrt", ".jp2")


def _safe_name(name):
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")[:60] or "layer"


def filename_stub(labels, limit=4, max_len=60):
    """A short, readable base for a download's file name, built from whatever says what's in it - a search
    term, description values, feature type names, classifications... - so e.g. 'bridge', 'Footbridge',
    'Pipe Bridge' becomes 'bridge_Footbridge_Pipe_Bridge' instead of a bare timestamp. Deduplicates
    case-insensitively and caps the count (adding '_and_N_more') and the length, so the name stays sane
    whatever was ticked. Every download tab uses this, so file names share one format."""
    parts, seen = [], set()
    for v in labels:
        safe = _safe_name(v) if v else ""
        key = safe.lower()
        if safe and key not in seen:
            parts.append(safe)
            seen.add(key)
    stub = "_".join(parts[:limit])[:max_len].strip("_")
    if len(parts) > limit:
        stub += f"_and_{len(parts) - limit}_more"
    return stub or "download"


def vector_sublayers(path):
    """[(uri, provider, name)] for every vector layer in a file (gpkg/shp/geojson/zip...)."""
    out = []
    try:
        details = QgsProviderRegistry.instance().querySublayers(path)
    except Exception:
        details = []
    for d in details:
        if d.type() == _VECTOR_LAYER:
            out.append((d.uri(), d.providerKey(), d.name() or os.path.splitext(os.path.basename(path))[0]))
    if not out and not path.lower().endswith(RASTER_EXT):
        lyr = QgsVectorLayer(path, "x", "ogr")
        if lyr.isValid():
            out.append((path, "ogr", os.path.splitext(os.path.basename(path))[0]))
    return out


def _writer(out_path, layer_name, fields, wkb, crs):
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = layer_name
    opts.fileEncoding = "UTF-8"
    if os.path.exists(out_path):
        opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
    return QgsVectorFileWriter.create(out_path, fields, wkb, crs, QgsCoordinateTransformContext(), opts)


def clip_layer(layer, aoi_bng, out_path, layer_name, mode="intersects", is_cancelled=None):
    """Writes the part of ``layer`` inside ``aoi_bng`` to a GeoPackage layer. Returns features written."""
    crs = layer.crs() if layer.crs().isValid() else BNG
    aoi = QgsGeometry(aoi_bng)
    if crs != BNG:
        aoi.transform(QgsCoordinateTransform(BNG, crs, QgsCoordinateTransformContext()))
    engine = QgsGeometry.createGeometryEngine(aoi.constGet())
    engine.prepareGeometry()
    wkb = layer.wkbType()
    geom_type = QgsWkbTypes.geometryType(wkb)
    cut_geometries = mode == "clip" and geom_type != _POINT
    if cut_geometries:
        wkb = QgsWkbTypes.multiType(wkb)
    writer = _writer(out_path, layer_name, layer.fields(), wkb, crs)
    if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
        raise RuntimeError(f"Could not write {out_path}: {writer.errorMessage()}")
    n = 0
    req = QgsFeatureRequest().setFilterRect(aoi.boundingBox())
    try:
        for f in layer.getFeatures(req):
            if is_cancelled and is_cancelled():
                break
            g = f.geometry()
            if g is None or g.isEmpty() or not engine.intersects(g.constGet()):
                continue
            if cut_geometries:
                cut = g.intersection(aoi)
                if cut is None or cut.isEmpty():
                    continue
                if QgsWkbTypes.geometryType(cut.wkbType()) != geom_type:
                    # e.g. a polygon touching the edge yields a line - keep only same-type parts
                    parts = [p for p in cut.asGeometryCollection()
                             if QgsWkbTypes.geometryType(p.wkbType()) == geom_type]
                    if not parts:
                        continue
                    cut = QgsGeometry.collectGeometry(parts)
                cut.convertToMultiType()
                g = cut
            out = QgsFeature(f)
            out.setGeometry(g)
            writer.addFeature(out)
            n += 1
    finally:
        del writer
    return n


def clip_file(path, aoi_bng, out_dir, mode="intersects", is_cancelled=None, log=None):
    """Clips every vector layer (and rasters) in ``path``. Returns list of (output, layer_name, count)."""
    log = log or (lambda m: None)
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    results = []
    if path.lower().endswith(RASTER_EXT):
        out = os.path.join(out_dir, f"{base}_clipped.tif")
        clip_raster(path, aoi_bng, out)
        return [(out, None, None)]
    out = os.path.join(out_dir, f"{base}_clipped.gpkg")
    for uri, provider, name in vector_sublayers(path):
        if is_cancelled and is_cancelled():
            break
        lyr = QgsVectorLayer(uri, name, provider)
        if not lyr.isValid():
            continue
        lname = _safe_name(name)
        n = clip_layer(lyr, aoi_bng, out, lname, mode, is_cancelled)
        log(f"{name}: {n:,} feature(s)")
        results.append((out, lname, n))
    return results


def clip_raster(path, aoi_bng, out_path):
    from osgeo import gdal
    src = QgsRasterLayer(path, "r")
    crs = src.crs() if src.isValid() and src.crs().isValid() else BNG
    aoi = QgsGeometry(aoi_bng)
    if crs != BNG:
        aoi.transform(QgsCoordinateTransform(BNG, crs, QgsCoordinateTransformContext()))
    with tempfile.TemporaryDirectory() as tmp:
        cut = os.path.join(tmp, "cutline.geojson")
        with open(cut, "w") as fh:
            json.dump({"type": "FeatureCollection",
                       # GeoJSON defaults to WGS84 - name the CRS so GDAL reads the outline correctly
                       "crs": {"type": "name", "properties": {"name": crs.authid() or "EPSG:27700"}},
                       "features": [{"type": "Feature", "properties": {},
                                     "geometry": json.loads(aoi.asJson(precision=3))}]}, fh)
        res = gdal.Warp(out_path, path, cutlineDSName=cut, cropToCutline=True, dstSRS=crs.toWkt() or None,
                        multithread=True, warpOptions=["NUM_THREADS=ALL_CPUS"],
                        creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"])
        if res is None:
            raise RuntimeError(f"Could not clip raster {path}")
        res = None
    return out_path


def geojsonseq_to_gpkg(seq_path, aoi_bng, out_path, layer_name, mode="intersects"):
    """OS NGD API results (GeoJSON lines, EPSG:27700) -> GeoPackage layer, clipped. Returns count."""
    lyr = QgsVectorLayer(seq_path, layer_name, "ogr")
    if not lyr.isValid():
        if os.path.getsize(seq_path) == 0:
            return 0
        raise RuntimeError(f"Could not read downloaded features for {layer_name}")
    lyr.setCrs(BNG)   # requested with crs=EPSG:27700; GeoJSON readers otherwise assume WGS84
    return clip_layer(lyr, aoi_bng, out_path, _safe_name(layer_name), mode)


# ---------------------------------------------------------------- fast clipping of downloaded files (GDAL)
VECTOR_EXT = (".gpkg", ".shp", ".geojson", ".json", ".gml", ".gdb", ".tab", ".mif", ".kml", ".sqlite", ".fgb", ".csv")


def _gdal():
    from osgeo import gdal, ogr, osr
    gdal.UseExceptions()
    ogr.UseExceptions()
    osr.UseExceptions()
    return gdal, ogr, osr


def unpack(paths, tmp_dir, is_cancelled=None):
    """ZIPs are extracted to ``tmp_dir``; other files are used where they are. Returns data file paths."""
    out = []
    for path in paths:
        if path.lower().endswith(".zip"):
            dest = os.path.join(tmp_dir, _safe_name(os.path.splitext(os.path.basename(path))[0]))
            with zipfile.ZipFile(path) as z:
                for m in z.infolist():
                    if is_cancelled and is_cancelled():
                        return out
                    if not m.is_dir():
                        z.extract(m, dest)
            for root, dirs, files in os.walk(dest):
                for d in list(dirs):
                    if d.lower().endswith(".gdb"):      # a File Geodatabase is a folder
                        out.append(os.path.join(root, d))
                        dirs.remove(d)
                for f in files:
                    if f.lower().endswith(VECTOR_EXT + RASTER_EXT) and not f.lower().endswith(".aux.xml"):
                        out.append(os.path.join(root, f))
        else:
            out.append(path)
    return out


def _aoi_for(aoi_bng, srs, ogr, osr):
    """The area as an OGR geometry in the layer's coordinate system."""
    g = ogr.CreateGeometryFromWkb(bytes(aoi_bng.asWkb()))
    bng = osr.SpatialReference()
    bng.ImportFromEPSG(27700)
    bng.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    if srs is not None and not srs.IsSame(bng):
        srs = srs.Clone()
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        g.AssignSpatialReference(bng)
        g.TransformTo(srs)
    return g


def _clip_vector_layer(gdal, ogr, osr, src_path, layer_name, aoi_bng, out_path, out_name, mode):
    """One layer -> ``out_name`` in ``out_path`` (appending if it exists). Returns features written."""
    ds = gdal.OpenEx(src_path, gdal.OF_VECTOR)
    lyr = ds.GetLayerByName(layer_name)
    aoi = _aoi_for(aoi_bng, lyr.GetSpatialRef(), ogr, osr)
    xmin, xmax, ymin, ymax = aoi.GetEnvelope()
    geom_type = ogr.GT_Flatten(lyr.GetGeomType())
    exists, max_fid = False, -1
    if os.path.exists(out_path):
        d = gdal.OpenEx(out_path, gdal.OF_VECTOR)
        ol = d.GetLayerByName(out_name)
        if ol is not None:
            exists = True
            r = d.ExecuteSQL(f'SELECT MAX("{ol.GetFIDColumn() or "fid"}") FROM "{out_name}"')
            f = r.GetNextFeature()
            max_fid = f.GetField(0) if f is not None and f.IsFieldSet(0) else -1
            d.ReleaseResultSet(r)
        d = None
    cut = mode == "clip" and geom_type not in (ogr.wkbPoint, ogr.wkbMultiPoint, ogr.wkbNone, ogr.wkbUnknown)
    opts = dict(clipSrc=aoi.ExportToWkt(), geometryType="PROMOTE_TO_MULTI") if cut else {}
    gdal.VectorTranslate(
        out_path, ds, format="GPKG", layers=[layer_name], layerName=out_name,
        accessMode=("append" if exists else ("update" if os.path.exists(out_path) else None)),
        spatFilter=[xmin, ymin, xmax, ymax], transactionSize=100000, **opts)
    ds = None
    d = gdal.OpenEx(out_path, gdal.OF_VECTOR | gdal.OF_UPDATE)
    ol = d.GetLayerByName(out_name)
    fid_col = ol.GetFIDColumn() or "fid"
    if not cut and not _is_rect(aoi):
        # keep-whole mode: the bounding-box filter also let through features near the shape but outside
        # it. GDAL tests the new features against the exact shape (in C++); the rest are deleted.
        out_aoi = _aoi_for(aoi_bng, ol.GetSpatialRef(), ogr, osr)
        ol.SetAttributeFilter(f'"{fid_col}" > {max_fid}')
        ol.SetSpatialFilter(out_aoi)
        keep = {f.GetFID() for f in ol}
        ol.SetSpatialFilter(None)
        drop = [f.GetFID() for f in ol if f.GetFID() not in keep]
        if drop:
            ol.StartTransaction()
            for fid in drop:
                ol.DeleteFeature(fid)
            ol.CommitTransaction()
    ol.SetAttributeFilter(f'"{fid_col}" > {max_fid}')
    n = ol.GetFeatureCount()
    d = None
    return n


def _is_rect(g):
    xmin, xmax, ymin, ymax = g.GetEnvelope()
    return abs(g.GetArea() - (xmax - xmin) * (ymax - ymin)) < 1e-6 * max(1.0, g.GetArea())


def clip_downloads(paths, aoi_bng, out_dir, base_name, mode="intersects", is_cancelled=None, log=None,
                   progress=None):
    """Clips every vector layer and raster in the downloaded files. Tiles are merged into one GeoPackage
    (``<out_dir>/<base_name>_clipped.gpkg``, one layer per theme) and one GeoTIFF.
    Returns [(output, layer_name or None for a raster, features or None)]."""
    gdal, ogr, osr = _gdal()
    log = log or (lambda m: None)
    os.makedirs(out_dir, exist_ok=True)
    out_gpkg = os.path.join(out_dir, f"{_safe_name(base_name)}_clipped.gpkg")
    if os.path.exists(out_gpkg):
        os.remove(out_gpkg)
    tmp = tempfile.mkdtemp(prefix="osdl_unzip_", dir=out_dir)
    results, counts, rasters = [], {}, []
    try:
        if progress:
            progress(0, "Unpacking")
        files = unpack(paths, tmp, is_cancelled)
        jobs = []
        for f in files:
            if f.lower().endswith(RASTER_EXT):
                rasters.append(f)
                continue
            try:
                ds = gdal.OpenEx(f, gdal.OF_VECTOR)
            except RuntimeError:
                continue
            for i in range(ds.GetLayerCount()):
                lyr = ds.GetLayerByIndex(i)
                if lyr.GetGeomType() != ogr.wkbNone:
                    jobs.append((f, lyr.GetName()))
            ds = None
        for k, (f, lname) in enumerate(jobs):
            if is_cancelled and is_cancelled():
                break
            out_name = _safe_name(lname)
            if progress:
                progress(100 * k / max(1, len(jobs) + len(rasters)), f"Clipping {lname} ({k + 1}/{len(jobs)})")
            try:
                n = _clip_vector_layer(gdal, ogr, osr, f, lname, aoi_bng, out_gpkg, out_name, mode)
            except RuntimeError as ex:
                log(f"{lname}: could not clip ({ex})")
                continue
            counts[out_name] = counts.get(out_name, 0) + n
        for name, n in counts.items():
            log(f"{name}: {n:,} feature(s)")
            results.append((out_gpkg, name, n))
        if rasters and not (is_cancelled and is_cancelled()):
            if progress:
                progress(95, "Clipping rasters")
            src = rasters[0]
            if len(rasters) > 1:
                src = os.path.join(tmp, "mosaic.vrt")
                gdal.BuildVRT(src, rasters)
            out = os.path.join(out_dir, f"{_safe_name(base_name)}_clipped.tif")
            clip_raster(src, aoi_bng, out)
            results.append((out, None, None))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return results
