"""OS NGD Data Linkages: how OS NGD feature types connect to each other, and the pure-Python logic that
finds those connections in downloaded features.

The register below is built from the OS NGD connectivity diagram and the *NGD Relationship Knowledge
Specification v2* (internal guidance). Every link records:

* ``holder``   - the feature type whose attribute stores the reference;
* ``target``   - the feature type it points at, and the ``key`` it is matched on (``osid``, ``usrn``,
  ``uprn`` or ``postcode``);
* ``fields``   - the attribute name(s) the reference is expected in on the holder. A value can be a single
  identifier, a list of identifiers, or a list of objects (a cross-reference table delivered inline, e.g.
  ``[{"siteid": ...}]``) - ``sub`` lists the key to read from each object;
* ``rev``      - attribute name(s) on the *target* that point back at the holder, used when the reference
  turns out to be stored the other way round;
* ``cls``      - the specification's confidence class: A explicit identifier, B network topology,
  C authoritative containment, D spatially derived;
* ``kind``     - ``id`` (stored in the data) or ``spatial`` (calculated from geometry, off by default).

Field names are the specification's best evidence; it warns they must be checked against the delivered
schema. So nothing here trusts them blindly: :func:`detect_field` looks for the listed names first and
then for any attribute whose name mentions the target (e.g. ``...siteid``), and every download reports
which attribute was actually used - or that the link wasn't found - in the ``ngd_link_register`` table.
"""

from __future__ import annotations

import json
import re

PLACES_ADDRESS = "places-address"     # pseudo feature type: addresses from OS Places, keyed by UPRN

# ---------------------------------------------------------------------------------------------- themes
# (theme, [(base id, title, note)]) in the order shown in the tree. A note starting "!" marks a feature
# type that can't be downloaded through the APIs this plugin uses (shown greyed out, for completeness).
THEMES = [
    ("Buildings", [
        ("bld-fts-building", "Building", ""),
        ("bld-fts-buildingpart", "Building Part", ""),
        ("bld-fts-buildingaccesslocation", "Building Access Location", ""),
        ("bld-fts-buildingline", "Building Line", ""),
    ]),
    ("Land Use", [
        ("lus-fts-site", "Site", ""),
        ("lus-fts-siteaccesslocation", "Site Access Location", ""),
        ("lus-fts-siteroutingpoint", "Site Routing Point", "legacy - end of life; routing moved to Road Node"),
    ]),
    ("Address", [
        (PLACES_ADDRESS, "Address (from OS Places, by UPRN)",
         "Built, Historic, Pre-build and Non-addressable addresses aren't in the OS NGD API - Features; "
         "they're read from the OS Places API (needs 'OS Places API' on the key)"),
        ("!add-street", "Street Address", "!not available through the APIs - use Street (USRN) instead"),
        ("!add-xref", "Related Entity / Other Classifications / Alternate Address",
         "!cross-reference tables only supplied through OS Select+Build"),
    ]),
    ("Land", [
        ("lnd-fts-land", "Land", ""),
        ("lnd-fts-landpoint", "Land Point", ""),
        ("lnd-fts-landform", "Landform", ""),
        ("lnd-fts-landformline", "Landform Line", ""),
        ("lnd-fts-landformpoint", "Landform Point", ""),
    ]),
    ("Structures", [
        ("str-fts-structure", "Structure", ""),
        ("str-fts-structureline", "Structure Line", ""),
        ("str-fts-structurepoint", "Structure Point", ""),
        ("str-fts-fieldboundary", "Field Boundary", ""),
        ("str-fts-compoundstructure", "Compound Structure", ""),
    ]),
    ("Water", [
        ("wtr-fts-water", "Water", ""),
        ("wtr-fts-waterpoint", "Water Point", ""),
        ("wtr-fts-tidalboundary", "Tidal Boundary", ""),
        ("wtr-fts-intertidalline", "Inter-tidal Line", ""),
        ("wtr-ntwk-waterlink", "Water Link", ""),
        ("wtr-ntwk-waternode", "Water Node", ""),
        ("wtr-ntwk-waterlinkset", "Water Link Set", ""),
    ]),
    ("Transport network", [
        ("trn-ntwk-roadlink", "Road Link", ""),
        ("trn-ntwk-roadnode", "Road Node", ""),
        ("trn-ntwk-road", "Road", ""),
        ("trn-ntwk-street", "Street", ""),
        ("trn-ntwk-roadjunction", "Road Junction", ""),
        ("trn-ntwk-pathlink", "Path Link", ""),
        ("trn-ntwk-pathnode", "Path Node", ""),
        ("trn-ntwk-path", "Path", ""),
        ("trn-ntwk-pavementlink", "Pavement Link", ""),
        ("trn-ntwk-connectinglink", "Connecting Link", ""),
        ("trn-ntwk-connectingnode", "Connecting Node", ""),
        ("trn-ntwk-railwaylink", "Railway Link", ""),
        ("trn-ntwk-railwaynode", "Railway Node", ""),
        ("trn-ntwk-railwaylinkset", "Railway Link Set", ""),
        ("trn-ntwk-ferrylink", "Ferry Link", ""),
        ("trn-ntwk-ferrynode", "Ferry Node", ""),
        ("trn-ntwk-ferryterminal", "Ferry Terminal", ""),
        ("trn-ntwk-cyclelane", "Cycle Lane", ""),
        ("trn-ntwk-buslane", "Bus Lane", ""),
        ("trn-ntwk-tramonroad", "Tram on Road", ""),
    ]),
    ("Transport features", [
        ("trn-fts-roadtrackorpath", "Road, Track or Path", ""),
        ("trn-fts-rail", "Rail", ""),
        ("trn-fts-roadline", "Road Line", ""),
        ("trn-fts-streetlight", "Street Light", ""),
        ("trn-fts-cartographicraildetail", "Cartographic Rail Detail", ""),
    ]),
    ("Routing and asset management (RAMI)", [
        ("trn-rami-averageandindicativespeed", "Average and Indicative Speed", ""),
        ("trn-rami-restriction", "Restriction", ""),
        ("trn-rami-routinghazard", "Routing Hazard", ""),
        ("trn-rami-routingstructure", "Routing Structure", ""),
        ("trn-rami-highwaydedication", "Highway Dedication", ""),
        ("trn-rami-maintenancearea", "Maintenance Area", ""),
        ("trn-rami-maintenanceline", "Maintenance Line", ""),
        ("trn-rami-maintenancepoint", "Maintenance Point", ""),
        ("trn-rami-reinstatementarea", "Reinstatement Area", ""),
        ("trn-rami-reinstatementline", "Reinstatement Line", ""),
        ("trn-rami-reinstatementpoint", "Reinstatement Point", ""),
        ("trn-rami-specialdesignationarea", "Special Designation Area", ""),
        ("trn-rami-specialdesignationline", "Special Designation Line", ""),
        ("trn-rami-specialdesignationpoint", "Special Designation Point", ""),
    ]),
    ("Geographical Names", [
        ("gnm-fts-namedpoint", "Named Point", ""),
        ("gnm-fts-namedarea", "Named Area", ""),
        ("gnm-fts-namedroadjunction", "Named Road Junction", ""),
        ("gnm-fts-crowdsourcednamepoint", "Crowd Sourced Name Point", ""),
    ]),
    ("Administrative and statistical units", [
        ("asu-gbpcd-postcodeunitpoint", "Postcode Unit Point", ""),
        ("asu-gbpcd-postcodeunitarea", "Postcode Unit Area", ""),
        ("!asu-admin", "Country, Region, Local Authorities, Wards, Parishes, Electoral Divisions, Polling "
                       "Districts", "!not served by the OS NGD API - Features"),
        ("!asu-retail", "Retail Areas (Minor, Major, Aggregated)", "!not served by the OS NGD API - Features"),
    ]),
]

TYPES = {}          # base id -> {"title", "theme", "note", "available"}
for _theme, _items in THEMES:
    for _bid, _title, _note in _items:
        TYPES[_bid] = {"title": _title, "theme": _theme, "note": _note.lstrip("!"),
                       "available": not _bid.startswith("!") and not _note.startswith("!"),
                       "legacy": _note.startswith("legacy")}


def title(base):
    return TYPES.get(base, {}).get("title", base)


def short(base):
    """A short, column-friendly name for a feature type: 'bld-fts-buildingpart' -> 'buildingpart'."""
    if base == PLACES_ADDRESS:
        return "address"
    return base.rsplit("-", 1)[-1]


# ---------------------------------------------------------------------------------------------- links
CLASSES = {
    "A": "Explicit identifier",
    "B": "Network topology",
    "C": "Authoritative containment",
    "D": "Spatially derived",
}
# the same classes in everyday words (tree, details panel, register)
PLAIN_CLASSES = {
    "A": ("Stored ID", "OS records the other feature's ID in the data"),
    "B": ("Network connection", "part of how the network is joined together"),
    "C": ("Sits within", "OS records what the feature lies inside"),
    "D": ("Worked out from location", "calculated by the plugin from where the features are - not supplied by "
                                      "OS, so treat it as a best guess"),
}

LINKS = []


def _link(lid, holder, target, label, fields=(), sub=(), key="osid", card="N:1", cls="A", rev=(), rev_sub=(),
          all_fields=False, kind="id", op=None, tol=None, note="", inverse="", match=None, when=None):
    LINKS.append({"match": match or {}, "when": when or {},
        "id": lid, "holder": holder, "target": target, "label": label, "inverse": inverse,
        "fields": list(fields), "sub": list(sub), "key": key, "card": card, "cls": cls,
        "rev": list(rev), "rev_sub": list(rev_sub), "all_fields": all_fields, "kind": kind,
        "op": op, "tol": tol, "note": note,
    })
    if not inverse:
        LINKS[-1]["inverse"] = (f"contains {title(holder)}" if kind == "spatial" and op == "within"
                                else f"is linked from {title(holder)}")


_SITE_FIELDS = ("smallestsite_siteid", "largestsite_siteid", "sitereference")   # sitereference: every Site (newer schemas)
# ---- Buildings
_link("building_primary_site", "bld-fts-building", "lus-fts-site", "lies in primary Site",
      ["primarysiteid", "primarysite_id"], card="N:1 (0..1)", cls="C",
      note="Primary Site OSID stored on the Building (zero or one).", inverse="is primary Site of Building")
_link("building_sites", "bld-fts-building", "lus-fts-site", "lies in Site (all)",
      ["sitereference", "siteid", "site_reference"], sub=["siteid"], card="N:M",
      note="Building-to-Site cross-reference table (Site Reference): every Site a building falls in.",
      inverse="contains Building")
_link("building_parts", "bld-fts-building", "bld-fts-buildingpart", "is made of Building Part",
      ["buildingpartreference", "buildingpartid", "buildingpart_reference"], sub=["buildingpartid"], card="1:N",
      rev=["buildingid", "buildingreference"], rev_sub=["buildingid"],
      note="Building-to-Building-Part cross-reference table: a Building is one or more connected parts.",
      inverse="is part of Building")
_link("building_uprn", "bld-fts-building", PLACES_ADDRESS, "has address (UPRN)",
      ["uprnreference", "uprn", "uprn_reference"], sub=["uprn"], key="uprn", card="1:N",
      note="Building-to-UPRN cross-reference table (UPRN Reference). Zero or more addresses per building.",
      inverse="is in Building")
_link("building_main", "bld-fts-building", "bld-fts-building", "main Building on the same Site",
      ["mainbuildingid", "mainbuilding_id"], card="N:1 (0..1)", inverse="is main Building for")
_link("bal_building", "bld-fts-buildingaccesslocation", "bld-fts-building", "is an entrance to Building",
      ["accessedbuildingid", "buildingid", "accessedbuilding_id"], card="N:1",
      rev=["buildingaccesslocationreference"], rev_sub=["buildingaccesslocationid"],
      inverse="has entrance")
# ---- Land Use
_link("sal_site", "lus-fts-siteaccesslocation", "lus-fts-site", "is an access to Site",
      ["accessedsiteid", "siteid"], card="N:1", note="accessedsiteid references the Site OSID.",
      inverse="has access location")
_link("sal_roadnode", "lus-fts-siteaccesslocation", "trn-ntwk-roadnode", "connects to Road Node",
      ["accessednetworknodeid", "networknodeid", "roadnodeid"], card="N:1", cls="B",
      when={"accessednetworknodefeaturetype": ["Road Network", "Road Node", "roadnode"]},
      note="accessednetworknodeid references the Road Node OSID - the way into the Site from the road "
           "network. distancetonetworknode_m is context, not connectivity.",
      inverse="is the network point for Site Access Location")
_link("sal_pathnode", "lus-fts-siteaccesslocation", "trn-ntwk-pathnode", "connects to Path Node",
      ["accessednetworknodeid", "networknodeid"], card="N:1", cls="B",
      when={"accessednetworknodefeaturetype": ["Path Network", "Path Node", "pathnode"]},
      note="Entrances reached from the path network rather than the road network.",
      inverse="is the network point for Site Access Location")
_link("site_uprn", "lus-fts-site", PLACES_ADDRESS, "has representative address (UPRN)",
      ["matcheduprn", "primaryuprn", "uprn"], key="uprn", card="N:1",
      note="The Site's matched / representative UPRN. Many more addresses can fall inside a Site - add the "
           "spatial 'Address inside Site' link for those.", inverse="is the representative address of Site")
_link("site_mainbuilding", "lus-fts-site", "bld-fts-building", "has main Building", ["mainbuildingid"],
      card="N:1 (0..1)", note="The principal Building at the Site.", inverse="is the main Building of Site")
_link("srp_site", "lus-fts-siteroutingpoint", "lus-fts-site", "is the routing point of Site",
      ["siteid", "routedsiteid"], card="N:1", note="Legacy feature type - routing moved to Road Node.")
for _bid in ("bld-fts-buildingpart", "lnd-fts-land", "str-fts-structure", "wtr-fts-water", "trn-fts-rail",
             "trn-fts-roadtrackorpath"):
    _link(f"{short(_bid)}_site", _bid, "lus-fts-site", "lies in Site (smallest & largest)",
          _SITE_FIELDS, sub=["siteid"], all_fields=True, card="N:M", cls="C",
          note="Topographic areas carry the smallest and largest Site they lie in, and inherit its land-use "
               "classification (Tier A/B). The link table says which (via_field).",
          inverse=f"contains {title(_bid)}")
# ---- Address (OS Places rows)
_link("address_parent", PLACES_ADDRESS, PLACES_ADDRESS, "has parent address (UPRN)", ["parent_uprn", "parentuprn"], key="uprn",
      card="N:1", note="Parent/child UPRNs, e.g. flats in a block.", inverse="has child address")
_link("address_street", PLACES_ADDRESS, "trn-ntwk-street", "is on Street (USRN)", ["usrn"], key="usrn",
      card="N:1", note="Needs LPI addresses from OS Places (the Royal Mail DPA record has no USRN) - "
                       "LPI is added automatically when this link is ticked.", inverse="has address")
_link("address_pcpoint", PLACES_ADDRESS, "asu-gbpcd-postcodeunitpoint", "is in postcode", ["postcode"],
      key="postcode", card="N:1", note="Postcode is a postal grouping, not a property key, and can change.",
      inverse="contains address")
_link("address_pcarea", PLACES_ADDRESS, "asu-gbpcd-postcodeunitarea", "is in postcode area", ["postcode"],
      key="postcode", card="N:1", inverse="contains address")
_link("pcpoint_pcarea", "asu-gbpcd-postcodeunitpoint", "asu-gbpcd-postcodeunitarea", "is the point of",
      ["postcode"], key="postcode", card="1:1", inverse="has point")
# ---- Networks: link -> node topology
for _l, _n, _c in (("trn-ntwk-roadlink", "trn-ntwk-roadnode", "B"), ("trn-ntwk-pathlink", "trn-ntwk-pathnode", "B"),
                   ("trn-ntwk-railwaylink", "trn-ntwk-railwaynode", "B"),
                   ("trn-ntwk-ferrylink", "trn-ntwk-ferrynode", "B"),
                   ("trn-ntwk-connectinglink", "trn-ntwk-connectingnode", "B"),
                   ("wtr-ntwk-waterlink", "wtr-ntwk-waternode", "B")):
    _link(f"{short(_l)}_nodes", _l, _n, f"starts / ends at {title(_n)}", ["startnode", "endnode"],
          all_fields=True, card="N:2", cls=_c, note="Start and end node references (via_field says which).",
          inverse=f"joins {title(_l)}")
_link("connectinglink_pathnode", "trn-ntwk-connectinglink", "trn-ntwk-pathnode", "connects to Path Node",
      ["pathnodeid", "pathnodereference", "startnode", "endnode"], sub=["pathnodeid"], all_fields=True,
      card="N:1", cls="B", note="Connecting Links bridge the road and path networks.",
      inverse="is joined by Connecting Link")
_link("connectingnode_roadnode", "trn-ntwk-connectingnode", "trn-ntwk-roadnode", "sits on Road Node",
      ["roadnodeid", "roadnodereference"], sub=["roadnodeid"], card="N:1", cls="B",
      rev=["connectingnodereference", "connectingnodeid"], rev_sub=["connectingnodeid"],
      inverse="has Connecting Node")
_link("railwaylink_set", "trn-ntwk-railwaylink", "trn-ntwk-railwaylinkset", "is a member of Railway Link Set",
      ["railwaylinksetreference", "railwaylinksetid"], sub=["railwaylinksetid"], card="N:1+", cls="B",
      rev=["railwaylinkreference", "railwaylinkid"], rev_sub=["railwaylinkid"],
      note="Railway Link reference table groups links into Railway Link Sets.", inverse="groups Railway Link")
_link("waterlink_set", "wtr-ntwk-waterlink", "wtr-ntwk-waterlinkset", "is a member of Water Link Set",
      ["waterlinksetreference", "waterlinksetid"], sub=["waterlinksetid"], card="N:1+", cls="B",
      rev=["waterlinkreference", "waterlinkid"], rev_sub=["waterlinkid"],
      note="Water Link reference table groups links into Water Link Sets.", inverse="groups Water Link")
_link("ferryterminal_ferrynode", "trn-ntwk-ferryterminal", "trn-ntwk-ferrynode", "uses Ferry Node",
      ["ferrynodereference", "ferrynodeid"], sub=["ferrynodeid"], card="N:M", cls="B",
      inverse="serves Ferry Terminal")
_link("ferryterminal_roadnode", "trn-ntwk-ferryterminal", "trn-ntwk-roadnode", "is reached from Road Node",
      ["roadnodereference", "roadnodeid"], sub=["roadnodeid"], card="N:M", cls="B",
      inverse="reaches Ferry Terminal")
_link("ferryterminal_pathnode", "trn-ntwk-ferryterminal", "trn-ntwk-pathnode", "is reached from Path Node",
      ["pathnodereference", "pathnodeid"], sub=["pathnodeid"], card="N:M", cls="B",
      inverse="reaches Ferry Terminal")
_link("roadnode_junction", "trn-ntwk-roadnode", "trn-ntwk-roadjunction", "is part of Road Junction",
      ["roadjunctionreference", "roadjunctionid"], sub=["roadjunctionid"], card="N:1",
      rev=["roadnodereference", "roadnodeid"], rev_sub=["roadnodeid"], inverse="is made of Road Node")
# ---- Road Link cross-references
_link("roadlink_street", "trn-ntwk-roadlink", "trn-ntwk-street", "is part of Street (USRN)",
      ["streetreference", "usrn"], sub=["usrn"], key="usrn", card="N:M",
      note="Street identity (USRN) - street, road geometry and street address are different concepts.",
      inverse="is carried by Road Link")
_link("roadlink_road", "trn-ntwk-roadlink", "trn-ntwk-road", "is part of named Road",
      ["roadreference", "roadid"], sub=["roadid"], card="N:M", rev=["roadlinkreference"], rev_sub=["roadlinkid"],
      inverse="is made of Road Link")
_link("roadlink_rtp", "trn-ntwk-roadlink", "trn-fts-roadtrackorpath", "runs over Road, Track or Path surface",
      ["roadtrackorpathreference", "roadtrackorpathid"], sub=["roadtrackorpathid"], card="N:M",
      note="Topographic surfaces give the physical extent; network links give connectivity.",
      inverse="carries Road Link")
_link("roadlink_pavement", "trn-ntwk-pavementlink", "trn-ntwk-roadlink", "runs beside Road Link",
      ["roadlinkreference", "roadlinkid"], sub=["roadlinkid"], card="N:1",
      rev=["pavementlinkreference", "pavementlinkid"], rev_sub=["pavementlinkid"], inverse="has Pavement Link")
# RAMI records list the network features they apply to in a shared Network Reference table
# (networkreferenceid + networkfeaturetype, e.g. Restriction Network Reference) - read just the Road Link rows
# for the Road Link link and the Road Node rows for the Road Node link
_NETREF = ["networkreference", "restrictionnetworkreference", "routinghazardnetworkreference",
           "routingstructurenetworkreference", "averageandindicativespeednetworkreference"]
for _bid in ("trn-ntwk-cyclelane", "trn-ntwk-buslane", "trn-ntwk-tramonroad", "trn-fts-streetlight",
             "trn-rami-restriction", "trn-rami-routinghazard", "trn-rami-routingstructure",
             "trn-rami-averageandindicativespeed", "trn-rami-highwaydedication"):
    _link(f"{short(_bid)}_roadlink", _bid, "trn-ntwk-roadlink", "applies to Road Link",
          ["roadlinkreference", "roadlinkid", "roadlink_reference", "linkid"] + _NETREF,
          sub=["roadlinkid", "networkreferenceid", "linkid"],
          card="N:M", rev=[f"{short(_bid)}reference"], rev_sub=[f"{short(_bid)}id"],
          match={"networkfeaturetype": ["Road Link", "roadlink"]}, inverse=f"has {title(_bid)}")
for _bid in ("trn-rami-restriction", "trn-rami-routinghazard", "trn-rami-routingstructure"):
    _link(f"{short(_bid)}_roadnode", _bid, "trn-ntwk-roadnode", "applies at Road Node",
          ["roadnodereference", "roadnodeid"] + _NETREF, sub=["roadnodeid", "networkreferenceid"], card="N:M", cls="B",
          match={"networkfeaturetype": ["Road Node", "roadnode"]}, inverse=f"has {title(_bid)}")
# Road Node -> Road, Track or Path (Road Track Or Path Reference table on the Road Node)
_link("roadnode_rtp", "trn-ntwk-roadnode", "trn-fts-roadtrackorpath", "sits on Road, Track or Path surface",
      ["roadtrackorpathreference", "roadtrackorpathid"], sub=["roadtrackorpathid"], card="N:M",
      inverse="has Road Node")
_link("pathlink_path", "trn-ntwk-pathlink", "trn-ntwk-path", "is part of named Path",
      ["pathreference", "pathid"], sub=["pathid"], card="N:M", rev=["pathlinkreference"], rev_sub=["pathlinkid"],
      inverse="is made of Path Link")
_link("pathlink_street", "trn-ntwk-pathlink", "trn-ntwk-street", "is part of Street (USRN)",
      ["streetreference", "usrn"], sub=["usrn"], key="usrn", card="N:M", inverse="is carried by Path Link")
for _bid in ("trn-rami-averageandindicativespeed", "trn-rami-highwaydedication", "trn-rami-maintenancearea",
             "trn-rami-maintenanceline", "trn-rami-maintenancepoint", "trn-rami-reinstatementarea",
             "trn-rami-reinstatementline", "trn-rami-reinstatementpoint", "trn-rami-specialdesignationarea",
             "trn-rami-specialdesignationline", "trn-rami-specialdesignationpoint"):
    _link(f"{short(_bid)}_street", _bid, "trn-ntwk-street", "applies to Street (USRN)",
          ["usrn", "streetreference"], sub=["usrn"], key="usrn", card="N:1",
          note="Street management and designation records are keyed on USRN.", inverse=f"has {title(_bid)}")
# ---- Names
_link("namedroadjunction_junction", "gnm-fts-namedroadjunction", "trn-ntwk-roadjunction", "names Road Junction",
      ["roadjunctionreference", "roadjunctionid"], sub=["roadjunctionid"], card="N:1",
      note="Verify the exact reference field in the schema - falls back to the spatial link if absent.",
      inverse="is named by")
_link("crowdsourced_uprn", "gnm-fts-crowdsourcednamepoint", PLACES_ADDRESS, "names address (UPRN)",
      ["matcheduprn", "uprn", "uprnreference"], sub=["uprn"], key="uprn", card="N:1", inverse="has crowd-sourced name")
_link("crowdsourced_street", "gnm-fts-crowdsourcednamepoint", "trn-ntwk-street", "names Street (USRN)",
      ["matchedusrn", "usrn", "streetreference"], sub=["usrn"], key="usrn", card="N:1", inverse="has crowd-sourced name")
_link("namedpoint_street", "gnm-fts-namedpoint", "trn-ntwk-street", "is on Street (USRN)",
      ["usrn", "streetreference"], sub=["usrn"], key="usrn", card="N:1", inverse="has Named Point")

# ---- from OS's UK Geospatial Entity Relationships model: joins the OS NGD API - Features can make
_link("site_addresses", "lus-fts-site", PLACES_ADDRESS, "has address (all UPRNs)",
      ["sitetoaddressreference", "siteaddressreference"], sub=["uprn"], key="uprn", card="1:N",
      note="Site-to-address cross-reference table: every address that belongs to the Site, not just its main one.",
      inverse="belongs to Site")
_link("street_roadlinks", "trn-ntwk-street", "trn-ntwk-roadlink", "is carried by Road Link",
      ["roadlinkreference", "roadlinkid"], sub=["roadlinkid"], card="1:N", cls="B",
      note="The Street's own list of the Road Links that carry it.", inverse="carries Street")
_link("street_pathlinks", "trn-ntwk-street", "trn-ntwk-pathlink", "is carried by Path Link",
      ["pathlinkreference", "pathlinkid"], sub=["pathlinkid"], card="1:N", cls="B",
      note="The Street's own list of the Path Links that carry it (footpaths, alleys).", inverse="carries Street")
_link("connectingnode_roadlink", "trn-ntwk-connectingnode", "trn-ntwk-roadlink", "lies on Road Link",
      ["roadlinkid", "roadlinkreference"], sub=["roadlinkid"], card="N:1", cls="B",
      note="Where the path network meets a road.", inverse="has Connecting Node")
_link("roadjunction_roadlink", "trn-ntwk-roadjunction", "trn-ntwk-roadlink", "includes Road Link",
      ["roadlinkreference", "roadlinkid"], sub=["roadlinkid"], card="1:N", cls="B",
      note="The Road Links that make up a junction, such as a roundabout.", inverse="is part of Road Junction")
_link("siteroutingpoint_roadlink", "lus-fts-siteroutingpoint", "trn-ntwk-roadlink", "is reached from Road Link",
      ["roadlinkid"], card="N:1", cls="B", note="Legacy - routing moved to Site Access Location.",
      inverse="reaches Site Routing Point")
_link("sal_routingpoint", "lus-fts-siteaccesslocation", "lus-fts-siteroutingpoint", "uses Site Routing Point",
      ["routingpointid"], card="N:1", note="Older Site Access Location versions only.",
      inverse="is used by Site Access Location")
_link("cyclelane_parent", "trn-ntwk-cyclelane", "trn-ntwk-cyclelane", "is part of Cycle Lane", ["parentid"],
      card="N:1", cls="C", inverse="contains Cycle Lane")
_link("ferryterminal_site", "trn-ntwk-ferryterminal", "lus-fts-site", "lies in Site", ["siteid"], card="N:1",
      cls="C", inverse="contains Ferry Terminal")
_link("fieldboundary_structureline", "str-fts-fieldboundary", "str-fts-structureline", "is drawn as Structure Line",
      ["structureline_osid", "structurelineid"], card="N:1", inverse="is a Field Boundary")
for _bid in ("lus-fts-site", "bld-fts-buildingpart", "str-fts-compoundstructure", "str-fts-structure",
             "str-fts-structureline", "str-fts-structurepoint", "lnd-fts-land", "lnd-fts-landpoint",
             "lnd-fts-landform", "lnd-fts-landformpoint", "wtr-fts-water", "wtr-fts-waterpoint",
             "wtr-ntwk-waterlinkset", "wtr-fts-intertidalline", "trn-ntwk-road", "trn-ntwk-roadnode",
             "trn-fts-roadtrackorpath", "gnm-fts-namedarea", "gnm-fts-namedroadjunction"):
    _link(f"crowdsourced_{short(_bid)}", "gnm-fts-crowdsourcednamepoint", _bid, f"names {title(_bid)}",
          ["matchedosid"], card="N:1", note="Crowd-sourced names are matched by OS to the feature they describe.",
          inverse="has crowd-sourced name")

# ---- Spatially derived (class D) - calculated from geometry, never stored. Off unless shown.
_SP = "Calculated from geometry, not an authoritative identifier link."
_link("sp_address_buildingpart", PLACES_ADDRESS, "bld-fts-buildingpart", "lies inside Building Part",
      kind="spatial", op="within", cls="D", card="N:1",
      note=_SP + " Watch for flats, campus addresses and addresses positioned outside footprints.")
_link("sp_address_building", PLACES_ADDRESS, "bld-fts-building", "lies inside Building", kind="spatial",
      op="within", cls="D", card="N:1", note=_SP + " Use when the Building UPRN cross-reference is missing.")
_link("sp_address_site", PLACES_ADDRESS, "lus-fts-site", "lies inside Site", kind="spatial", op="within",
      cls="D", card="N:M", note=_SP + " Every address inside the Site, not just its representative UPRN.")
_link("sp_address_pcarea", PLACES_ADDRESS, "asu-gbpcd-postcodeunitarea", "lies inside postcode area",
      kind="spatial", op="within", cls="D", card="N:1", note=_SP)
_link("sp_buildingpart_building", "bld-fts-buildingpart", "bld-fts-building", "lies inside Building",
      kind="spatial", op="within", cls="D", card="N:1",
      note=_SP + " A Building is derived by merging connected Building Parts in the same Site.")
_link("sp_building_pcarea", "bld-fts-building", "asu-gbpcd-postcodeunitarea", "centre lies in postcode area",
      kind="spatial", op="within", cls="D", card="N:1", note=_SP)
_link("sp_bal_building", "bld-fts-buildingaccesslocation", "bld-fts-building", "is on the edge of Building",
      kind="spatial", op="nearest", tol=2.0, cls="D", card="N:1", note=_SP + " Nearest Building within 2 m.")
_link("sp_sal_site", "lus-fts-siteaccesslocation", "lus-fts-site", "is on the edge of Site", kind="spatial",
      op="nearest", tol=2.0, cls="D", card="N:1", note=_SP + " Nearest Site within 2 m.")
_link("sp_namedpoint_site", "gnm-fts-namedpoint", "lus-fts-site", "lies inside Site", kind="spatial",
      op="within", cls="D", card="N:M", note=_SP)
_link("sp_namedroadjunction_junction", "gnm-fts-namedroadjunction", "trn-ntwk-roadjunction",
      "overlaps Road Junction", kind="spatial", op="nearest", tol=25.0, cls="D", card="N:1",
      note=_SP + " Nearest Road Junction within 25 m.")
_link("sp_streetlight_roadlink", "trn-fts-streetlight", "trn-ntwk-roadlink", "is beside Road Link",
      kind="spatial", op="nearest", tol=25.0, cls="D", card="N:1", note=_SP + " Nearest Road Link within 25 m.")
_link("sp_structurepoint_site", "str-fts-structurepoint", "lus-fts-site", "lies inside Site", kind="spatial",
      op="within", cls="D", card="N:M", note=_SP)
_link("sp_landpoint_site", "lnd-fts-landpoint", "lus-fts-site", "lies inside Site", kind="spatial",
      op="within", cls="D", card="N:M", note=_SP)

_link("sp_building_site", "bld-fts-building", "lus-fts-site", "lies inside Site", kind="spatial", op="within",
      cls="D", card="N:M", note=_SP + " Used when the Building's Site reference isn't in the data.")

# When OS's identifier link isn't in the downloaded data, it is worked out from location instead:
# {identifier link: (spatial link, swap)} - swap when the spatial link runs the other way round.
FALLBACK = {
    "building_uprn": ("sp_address_building", True),
    "building_parts": ("sp_buildingpart_building", True),
    "building_sites": ("sp_building_site", False),
    "building_primary_site": ("sp_building_site", False),
    "bal_building": ("sp_bal_building", False),
    "sal_site": ("sp_sal_site", False),
    "namedroadjunction_junction": ("sp_namedroadjunction_junction", False),
}

LINK_BY_ID = {lk["id"]: lk for lk in LINKS}

# ---------------------------------------------------------------------------------------------- plain English
_PLURAL = {"Address (from OS Places, by UPRN)": "Addresses", "Land": "Land areas", "Water": "Water areas",
           "Rail": "Rail areas", "Road, Track or Path": "Road, Track or Path areas",
           "Average and Indicative Speed": "Average and Indicative Speed records", "Tram on Road": "Tram on Road sections",
           "Highway Dedication": "Highway Dedications", "Site Routing Point": "Site Routing Points"}


def plural(base):
    t = title(base)
    if t in _PLURAL:
        return _PLURAL[t]
    return t + ("es" if t.endswith(("s", "sh", "ch")) else "s")


_SINGULAR = {"Land": "Land area", "Water": "Water area", "Rail": "Rail area",
             "Road, Track or Path": "Road, Track or Path area", "Average and Indicative Speed": "Speed record"}


def noun(base):
    """'Address' rather than 'Address (from OS Places, by UPRN)'; 'Land area' rather than 'Land'."""
    t = title(base).split(" (")[0]
    return _SINGULAR.get(t, t)


# How each link reads, from each end: (under the holder, under the target). {H}/{T} = plural holder/target.
_SAY = {
    "building_primary_site": ("the Site it mainly belongs to", "Buildings that mainly belong to this Site"),
    "building_sites": ("every Site it falls within", "every Building that falls within this Site"),
    "building_parts": ("the Building Parts it's made of", "the Building it's part of"),
    "building_uprn": ("its addresses (UPRNs)", "the Building this address is in"),
    "building_main": ("the main Building on the same Site", "Buildings that have this as their main Building"),
    "bal_building": ("the Building it's an entrance to", "its entrances (Building Access Locations)"),
    "sal_site": ("the Site it's an entrance to", "its entrances (Site Access Locations)"),
    "sal_roadnode": ("the Road Node where it joins the road network", "Site entrances that join the road here"),
    "site_uprn": ("its main address (UPRN)", "the Site this is the main address of"),
    "srp_site": ("the Site it's the routing point for (old data)", "its routing points (old data)"),
    "address_parent": ("its parent address (e.g. the block a flat is in)",
                       "its child addresses (e.g. the flats in this block)"),
    "address_street": ("the Street it's on (USRN)", "addresses on this Street"),
    "address_pcpoint": ("its postcode point", "addresses in this postcode"),
    "address_pcarea": ("its postcode area", "addresses in this postcode area"),
    "pcpoint_pcarea": ("the postcode area it belongs to", "the postcode point for this area"),
    "connectinglink_pathnode": ("the Path Node it connects to", "Connecting Links that join here"),
    "connectingnode_roadnode": ("the Road Node it sits on", "Connecting Nodes on this Road Node"),
    "railwaylink_set": ("the Railway Link Set(s) it belongs to", "the Railway Links in this set"),
    "waterlink_set": ("the Water Link Set(s) it belongs to", "the Water Links in this set"),
    "ferryterminal_ferrynode": ("the Ferry Nodes it serves", "Ferry Terminals served from here"),
    "ferryterminal_roadnode": ("the Road Nodes you reach it from", "Ferry Terminals reached from here"),
    "ferryterminal_pathnode": ("the Path Nodes you reach it from", "Ferry Terminals reached from here"),
    "roadnode_junction": ("the Road Junction it's part of", "the Road Nodes that make up this junction"),
    "roadlink_street": ("the Street(s) it belongs to (USRN)", "Road Links that make up this Street"),
    "roadlink_road": ("the named Road it's part of", "Road Links that make up this Road"),
    "roadlink_rtp": ("the road surface areas it runs over", "Road Links running over this surface"),
    "roadlink_pavement": ("the Road Link it runs beside", "pavements beside this Road Link"),
    "pathlink_path": ("the named Path it's part of", "Path Links that make up this Path"),
    "pathlink_street": ("the Street(s) it belongs to (USRN)", "Path Links that make up this Street"),
    "namedroadjunction_junction": ("the Road Junction it names", "its name (Named Road Junction)"),
    "crowdsourced_uprn": ("the address it names (UPRN)", "local names for this address"),
    "crowdsourced_street": ("the Street it names (USRN)", "local names for this Street"),
    "namedpoint_street": ("the Street it's on (USRN)", "Named Points on this Street"),
    "sp_address_buildingpart": ("the Building Part it sits inside", "addresses sitting inside it"),
    "sp_address_building": ("the Building it sits inside", "addresses sitting inside it"),
    "sp_address_site": ("the Site(s) it sits inside", "addresses sitting inside this Site"),
    "sp_address_pcarea": ("the postcode area it sits inside", "addresses sitting inside it"),
    "sp_buildingpart_building": ("the Building it sits inside", "Building Parts sitting inside it"),
    "sp_building_pcarea": ("the postcode area its centre is in", "Buildings centred in this postcode area"),
    "sp_bal_building": ("the nearest Building (within 2 m)", "entrance points on its edge"),
    "sp_sal_site": ("the nearest Site (within 2 m)", "access points on its edge"),
    "sp_namedpoint_site": ("the Site it sits inside", "Named Points inside this Site"),
    "sp_namedroadjunction_junction": ("the nearest Road Junction (within 25 m)", "junction names nearby"),
    "sp_streetlight_roadlink": ("the nearest Road Link (within 25 m)", "Street Lights beside it"),
    "sp_structurepoint_site": ("the Site it sits inside", "Structure Points inside this Site"),
    "sp_landpoint_site": ("the Site it sits inside", "Land Points inside this Site"),
    "sp_building_site": ("the Site(s) it sits inside", "Buildings sitting inside this Site"),
    "site_mainbuilding": ("its main Building", "the Site this is the main Building of"),
    "sal_pathnode": ("the Path Node where it joins the path network", "Site entrances that join the path here"),
    "roadnode_rtp": ("the road surface areas it sits on", "Road Nodes on this surface"),
    "site_addresses": ("every address that belongs to it", "the Site this address belongs to"),
    "street_roadlinks": ("the Road Links that carry it", "the Streets this Road Link carries"),
    "street_pathlinks": ("the Path Links that carry it", "the Streets this Path Link carries"),
    "connectingnode_roadlink": ("the Road Link it sits on", "where paths join this Road Link"),
    "roadjunction_roadlink": ("the Road Links that make it up", "the Road Junction it's part of"),
    "siteroutingpoint_roadlink": ("the Road Link it's reached from", "Site Routing Points reached from here"),
    "sal_routingpoint": ("its Site Routing Point (older versions)", "Site entrances using this routing point"),
    "cyclelane_parent": ("the Cycle Lane it's part of", "the stretches that make up this Cycle Lane"),
    "ferryterminal_site": ("the Site it lies in", "Ferry Terminals on this Site"),
    "fieldboundary_structureline": ("the Structure Line that draws it", "the Field Boundary it draws"),
}
for _bid in ("lus-fts-site", "bld-fts-buildingpart", "str-fts-compoundstructure", "str-fts-structure",
             "str-fts-structureline", "str-fts-structurepoint", "lnd-fts-land", "lnd-fts-landpoint",
             "lnd-fts-landform", "lnd-fts-landformpoint", "wtr-fts-water", "wtr-fts-waterpoint",
             "wtr-ntwk-waterlinkset", "wtr-fts-intertidalline", "trn-ntwk-road", "trn-ntwk-roadnode",
             "trn-fts-roadtrackorpath", "gnm-fts-namedarea", "gnm-fts-namedroadjunction"):
    _SAY[f"crowdsourced_{short(_bid)}"] = (f"the {title(_bid)} it names", "the local names people use for it")
for _lk in LINKS:
    _id = _lk["id"]
    if _id in _SAY:
        _f, _b = _SAY[_id]
    elif _id.endswith("_nodes"):
        _f, _b = f"the {plural(_lk['target'])} it starts and ends at", f"{plural(_lk['holder'])} that start or end here"
    elif _id.endswith("_site"):
        _f, _b = "the Sites it lies in (smallest and largest)", f"{plural(_lk['holder'])} lying in this Site"
    elif _id.endswith("_roadlink"):
        _f, _b = "the Road Links it applies to", f"{plural(_lk['holder'])} on this Road Link"
    elif _id.endswith("_roadnode"):
        _f, _b = "the Road Nodes it applies at", f"{plural(_lk['holder'])} at this Road Node"
    elif _id.endswith("_street"):
        _f, _b = "the Street it applies to (USRN)", f"{plural(_lk['holder'])} for this Street"
    else:  # pragma: no cover - every link above is covered
        _f, _b = _lk["label"], _lk["inverse"]
    _lk["fwd"], _lk["back"] = _f, _b

_CARD = {
    "N:1": "Each {h} links to one {t}; one {t} can have many {H}.",
    "N:1 (0..1)": "Each {h} links to one {t} at most (some to none); one {t} can have many {H}.",
    "1:N": "Each {h} can link to several {T}; each of those links back to one {h}.",
    "N:M": "Each {h} can link to several {T}, and each {t} to several {H}.",
    "N:2": "Each {h} has a start and an end {t}; one {t} can join many {H}.",
    "N:1+": "Each {h} belongs to one or more {T}; each {t} groups many {H}.",
    "1:1": "Each {h} matches one {t}.",
}


def card_sentence(lk):
    """The cardinality in words, e.g. 'Each Building links to one Site; one Site can have many Buildings.'"""
    text = _CARD.get(lk["card"], "")
    return text.format(h=noun(lk["holder"]), t=noun(lk["target"]), H=plural(lk["holder"]),
                       T=plural(lk["target"]))


def say(lk, side="out"):
    """'Building → the Site it mainly belongs to' (side 'out') or 'Site ← Buildings that mainly belong to this
    Site' (side 'in')."""
    if side == "out":
        return f"{noun(lk['holder'])} → {lk['fwd']}"
    return f"{noun(lk['target'])} ← {lk['back']}"


def links_for(base, kind=None):
    """Every link with ``base`` at either end (optionally only ``kind`` 'id' or 'spatial')."""
    return [lk for lk in LINKS if base in (lk["holder"], lk["target"]) and (kind is None or lk["kind"] == kind)]


# ---------------------------------------------------------------------------------------------- quick picks
# Organised around the questions people ask, not around OS themes. Each ticks the feature types and links
# that answer it; 'filters' narrows a feature type by description (e.g. only School sites). Spatial links
# (worked out from location) are listed too but only ticked when 'Show spatial links' is on - off by default.
A = PLACES_ADDRESS
EDUCATION_SITES = ["School", "College", "University", "University College", "University School",
                   "Children's Nursery", "Children's Centre", "Pupil Referral Site", "Education Support Site"]
UTILITY_SITES = ["Electricity Distribution Site", "Electricity Storage Site", "Electricity Sub Station",
                 "Gas Distribution Or Storage Site", "Gas Governor", "Gas Production Site", "Power Station",
                 "Solar Power Site", "Telecommunications Site", "Pumping Station", "Water Distribution Site",
                 "Water Treatment Site", "Waste Water Treatment Works"]

RECIPES = [
    {"name": "1. Property and address intelligence",
     "question": "Tell me everything about this property.",
     "path": "Address → Building → Building Part → Site → land use",
     "answers": "Which building contains this address? How many addresses are in it? Residential, commercial or "
                "mixed use? Which site does it belong to - a university, hospital, industrial estate?",
     "types": [A, "bld-fts-building", "bld-fts-buildingpart", "lus-fts-site"],
     "links": ["building_uprn", "building_parts", "building_primary_site", "building_sites", "buildingpart_site",
               "site_uprn", "address_parent"],
     "note": "Land use (Tier A / B) is on the Site and on each Building Part. Building ↔ address comes from "
             "OS's own cross-reference, not location."},
    {"name": "2. Site understanding",
     "question": "What makes up this site?",
     "path": "Site → buildings, addresses, roads, structures, land, water, entrances",
     "answers": "All the buildings in a hospital site, its entrances and exits, all its addresses, its roads and "
                "internal infrastructure.",
     "types": ["lus-fts-site", "bld-fts-building", "bld-fts-buildingpart", A, "trn-fts-roadtrackorpath",
               "str-fts-structure", "lnd-fts-land", "wtr-fts-water", "trn-fts-rail", "lus-fts-siteaccesslocation"],
     "links": ["building_primary_site", "building_sites", "buildingpart_site", "roadtrackorpath_site",
               "structure_site", "land_site", "water_site", "rail_site", "sal_site", "site_uprn", "building_uprn",
               "sp_address_site"],
     "note": "Complete land-use coverage comes from Land Use + Buildings + Land + Structures + Transport + Water "
             "together. A site's addresses come through its buildings (OS's cross-references); tick 'Show spatial "
             "links' to also count every address point inside the site boundary."},
    {"name": "3. Emergency services access",
     "question": "How do I get into this site?",
     "path": "Site → Site Access Location → Road Node → Road Link",
     "answers": "Nearest emergency entrance, best vehicle access point, public vs private access, distance from "
                "the entrance to the road network; restrictions and barriers on the way.",
     "types": ["lus-fts-site", "lus-fts-siteaccesslocation", "trn-ntwk-roadnode", "trn-ntwk-roadlink",
               "bld-fts-building", "bld-fts-buildingaccesslocation", "trn-rami-restriction",
               "trn-rami-routingstructure"],
     "links": ["sal_site", "sal_roadnode", "roadlink_nodes", "building_primary_site", "bal_building",
               "restriction_roadlink", "routingstructure_roadlink"],
     "note": "Each entrance's access_purpose (Emergency, Public, Private…) and distancetonetworknode_m are in "
             "the Site Access Location layer."},
    {"name": "4. Building context",
     "question": "What surrounds this building?",
     "path": "Building → Site → address → postcode / street → roads",
     "answers": "Which postcode? Which street? Nearest roads? Which site, and what's nearby?",
     "types": ["bld-fts-building", "bld-fts-buildingpart", "lus-fts-site", A, "asu-gbpcd-postcodeunitpoint",
               "asu-gbpcd-postcodeunitarea", "trn-ntwk-street", "trn-ntwk-roadlink"],
     "links": ["building_primary_site", "building_uprn", "building_parts", "address_pcpoint", "address_pcarea",
               "address_street",
               "roadlink_street", "sp_building_pcarea"],
     "note": "Local authority and ward boundaries aren't served by the OS NGD API - the postcode is the "
             "nearest stand-in here (add Boundary-Line from OS Data Packages for the rest)."},
    {"name": "5. Education analysis",
     "question": "Which addresses does this school serve, and how accessible is it?",
     "path": "School Site → buildings → addresses → entrances → road network",
     "answers": "Which addresses are on the school site? What entrances exist? Which roads give access?",
     "types": ["lus-fts-site", "bld-fts-building", "bld-fts-buildingaccesslocation", A,
               "lus-fts-siteaccesslocation", "trn-ntwk-roadnode", "trn-ntwk-roadlink", "lnd-fts-land",
               "bld-fts-buildingpart"],
     "links": ["building_primary_site", "building_sites", "building_uprn", "site_uprn", "bal_building", "sal_site",
               "sal_roadnode", "roadlink_nodes", "sp_address_site", "land_site", "buildingpart_site"],
     "filters": {"lus-fts-site": EDUCATION_SITES},
     "note": "Sites are narrowed to education sites (schools, colleges, universities, nurseries…) - double-click "
             "Site to change that. Other buildings in the area still come down; their joined copy says which "
             "site they belong to."},
    {"name": "6. Transport impact assessment",
     "question": "What does this road serve?",
     "path": "Road Link → Road Node → Site Access Location → Site → buildings",
     "answers": "Which schools or hospitals use this road? What would a closure cut off?",
     "types": ["trn-ntwk-roadlink", "trn-ntwk-roadnode", "lus-fts-siteaccesslocation", "lus-fts-site",
               "bld-fts-building", "trn-ntwk-street"],
     "links": ["roadlink_nodes", "sal_roadnode", "sal_site", "building_primary_site", "roadlink_street"],
     "note": "In the Road Node's joined copy, n_siteaccesslocation counts the site entrances that join the road "
             "there."},
    {"name": "7. Utility and infrastructure discovery",
     "question": "Which buildings, structures and addresses belong to a utility site?",
     "path": "Structure → Site → Building → Address",
     "answers": "Which substation or pumping station is on which site? Which buildings belong to it? Which "
                "addresses are associated?",
     "types": ["str-fts-structure", "str-fts-structurepoint", "lus-fts-site", "bld-fts-building", A,
               "lnd-fts-land"],
     "links": ["structure_site", "sp_structurepoint_site", "building_primary_site", "building_uprn", "site_uprn",
               "land_site"],
     "filters": {"lus-fts-site": UTILITY_SITES},
     "note": "Sites are narrowed to utility sites (electricity, gas, water, telecoms…) - double-click Site to "
             "change that."},
    {"name": "8. Asset management",
     "question": "What's on each site, and how many addresses does it have?",
     "path": "Address → Building → Site",
     "answers": "Buildings within each site, addresses per site, the main building of each site.",
     "types": [A, "bld-fts-building", "lus-fts-site"],
     "links": ["building_uprn", "building_primary_site", "building_sites", "building_main", "site_uprn",
               "sp_address_site"],
     "note": "The Site's joined copy counts its buildings (n_building_…) and addresses (n_address_sp). To find "
             "council-owned sites, filter the addresses on their classification."},
    {"name": "9. Land use exploration",
     "question": "What is this area used for?",
     "path": "Land, buildings, water… → Site → land use Tier A → Tier B",
     "answers": "The activity behind each piece of land, building and water, and the site it belongs to.",
     "types": ["lus-fts-site", "lnd-fts-land", "bld-fts-buildingpart", "wtr-fts-water", "str-fts-structure",
               "trn-fts-rail", "trn-fts-roadtrackorpath"],
     "links": ["land_site", "buildingpart_site", "water_site", "structure_site", "rail_site",
               "roadtrackorpath_site"],
     "note": "Every topographic area carries its land-use Tier A / Tier B (oslandusetiera / oslandusetierb) "
             "and the smallest and largest Site it lies in."},
]
# The simple answer for each question: ONE layer, one row per 'subject' feature, with friendly columns
# gathered along the links. Column: (column, alias, path of link ids from the subject, how, attributes)
# - how 'attr' (first value of the first attribute that exists), 'list' (all values, comma-separated) or
# 'count' (how many linked features). An empty path reads the subject itself.
# ---- attribute names (current schema first, older names after - the first one present is used)
_DESC = ["description"]
_SITE_NAME = ["name1_text", "distinctivename", "name"]
_TIER_A = ["oslandusetiera"]
_TIER_B = ["oslandusetierb"]
_STREET = ["designatedname1_text", "name1_text", "localname1_text", "descriptor1_text"]
_CLASS = ["class_group"]
_AREA = ["geometry_area_m2", "geometry_area", "ngd_area_m2"]
_LENGTH = ["geometry_length_m", "geometry_length", "ngd_length_m"]
_FLOORS = ["numberoffloors"]
_HEIGHT = ["height_relativemax_m", "relativeheightmaximum"]
_EAVES = ["height_relativeroofbase_m", "relativeheightroofbase"]
_AGE = ["buildingage_period"]
_YEAR = ["buildingage_year"]
_MATERIAL = ["constructionmaterial"]
_ROOF = ["roofmaterial_primarymaterial"]
_ROOF_SHAPE = ["roofshapeaspect_shape"]
_SOLAR = ["roofmaterial_solarpanelpresence"]
_GREEN_ROOF = ["roofmaterial_greenroofpresence"]
_BASEMENT = ["basementpresence"]
_CONNECT = ["connectivity"]
_BUSE = ["buildinguse", "description"]
_LA = ["lowertierlocalauthority_gsscode"]
_STATE = ["physicalstate", "status"]
_ROOF_S = ["roofshapeaspect_areafacingsouth_m2"]
_ROOF_SE = ["roofshapeaspect_areafacingsoutheast_m2"]
_ROOF_SW = ["roofshapeaspect_areafacingsouthwest_m2"]
_ROOF_FLAT = ["roofshapeaspect_areaflat_m2"]
_OS_ADDR_TOTAL = ["addresscount_total", "buildinguse_addresscount_total"]
_OS_ADDR_RES = ["addresscount_residential", "buildinguse_addresscount_residential"]
_OS_ADDR_COM = ["addresscount_commercial", "buildinguse_addresscount_commercial"]

# land cover groups (Land 'description' values) for site composition
_GRASS = ("{d} LIKE '%Grass%' OR {d} LIKE '%Grazing%' OR {d} LIKE '%Heath%' OR {d} LIKE '%Marsh%' OR "
          "{d} = 'Games Court' OR {d} = 'Tennis Court' OR {d} = 'Gallops'")
_TREES = "{d} LIKE '%Trees%' OR {d} LIKE '%Scrub%' OR {d} = 'Orchard' OR {d} = 'Vineyard'"
_MADE = ("{d} LIKE 'Made Surface%' OR {d} IN ('Slipway', 'Steps', 'Sloping Masonry', 'Runway', 'Taxiway', "
         "'Helipad', 'Livestock Pen', 'Construction Site')")
_GARDEN = "{d} = 'Residential Garden'"


def _agg(fn, expr, where=None, **use):
    """An aggregate over the linked features: fn SUM / MAX / MIN / COUNT; expr and where use {placeholders}
    filled from ``use`` (name -> candidate attributes; a name ending '?' may be missing)."""
    return {"fn": fn, "expr": expr, "where": where, "use": use}


def _mix(path, what="addresses"):
    """Address type breakdown columns for the addresses reached along ``path``: '34 Residential (72%) /
    12 Commercial (26%)…' plus % residential, % commercial and % mixed use (numbers, for sorting/colouring)."""
    return [("address_mix", f"{what[:1].upper()}{what[1:]} by type", path, "breakdown", _CLASS),
            ("pct_residential", "% residential", path, "pct:Residential", _CLASS),
            ("pct_commercial", "% commercial", path, "pct:Commercial", _CLASS),
            ("pct_mixed_use", "% mixed use", path, "pct:Dual use (residential and commercial)", _CLASS)]


def _mix_counts(path):
    """How many of the addresses along ``path`` are residential, commercial or mixed use (numbers)."""
    return [(f"{name}_addresses", f"{alias} addresses", path, "agg", _agg("COUNT", "*", f"{{c}} = '{value}'", c=_CLASS))
            for name, alias, value in (("residential", "Residential", "Residential"),
                                       ("commercial", "Commercial", "Commercial"),
                                       ("mixed_use", "Mixed-use", "Dual use (residential and commercial)"))]


def _derive(name, alias, sql):
    """A column worked out from other answer columns, e.g. floor area = footprint x floors."""
    return (name, alias, None, "=", sql)


def _building(path=()):
    """Everything NGD holds about a building (reached along ``path``)."""
    p = list(path)
    return [
        ("building_use", "Building use", p, "attr", _BUSE),
        ("building_type", "Building", p, "attr", _DESC),
        ("connectivity", "Detached / semi / terrace", p, "attr", _CONNECT),
        ("building_age", "Built (period)", p, "attr", _AGE),
        ("year_built", "Year built", p, "attr", _YEAR),
        ("floors", "Floors", p, "attr", _FLOORS),
        ("height_m", "Height (m)", p, "attr", _HEIGHT),
        ("eaves_height_m", "Eaves height (m)", p, "attr", _EAVES),
        ("construction", "Construction material", p, "attr", _MATERIAL),
        ("roof_material", "Roof material", p, "attr", _ROOF),
        ("roof_shape", "Roof shape", p, "attr", _ROOF_SHAPE),
        ("solar_panels", "Solar panels", p, "attr", _SOLAR),
        ("green_roof", "Green roof", p, "attr", _GREEN_ROOF),
        ("basement", "Basement", p, "attr", _BASEMENT),
        ("building_state", "Condition", p, "attr", _STATE),
        ("footprint_m2", "Footprint (m²)", p, "attr", _AREA),
        ("south_roof_m2", "South-facing roof (m²)", p, "agg", _agg(
            "SUM", "COALESCE({s?}, 0) + COALESCE({se?}, 0) + COALESCE({sw?}, 0)", s=_ROOF_S, se=_ROOF_SE, sw=_ROOF_SW)),
        ("flat_roof_m2", "Flat roof (m²)", p, "attr", _ROOF_FLAT),
        _derive("floor_area_m2", "Floor area, est. (m²)", "ROUND(footprint_m2 * COALESCE(floors, 1))"),
    ]


def _site_composition(area_col="site_area_m2", land="land_site", parts="buildingpart_site",
                      water="water_site", roads="roadtrackorpath_site"):
    """How a site's ground is used: m² and % of the site under buildings, grass, trees, made surface,
    gardens, water and road/track/path - from the features that OS records as lying in the site."""
    cols = []
    for name, alias, path, where in (
            ("buildings", "under buildings", parts, None), ("grass", "grass / open ground", land, _GRASS),
            ("trees", "trees / scrub", land, _TREES), ("made_surface", "made surface (paved)", land, _MADE),
            ("gardens", "gardens", land, _GARDEN), ("water", "water", water, None),
            ("roads_paths", "roads, tracks and paths", roads, None)):
        if path is None:
            continue
        cols.append((f"{name}_m2", f"Area {alias} (m²)", [path], "agg",
                     _agg("SUM", "{a}", where, a=_AREA, d=_DESC)))
        cols.append(_derive(f"pct_{name}", f"% {alias}", f"ROUND(100.0 * {name}_m2 / NULLIF({area_col}, 0), 1)"))
    return cols


# a Site's addresses come through its buildings (OS's own cross-references: Site <- Building -> UPRN), so they
# need no spatial links; 'inside by location' is an extra, filled only when spatial links are ticked
_SITE_ADDR_PATH = ["building_primary_site", "building_uprn"]


def _site_addresses():
    return [("addresses", "Addresses (in its buildings)", _SITE_ADDR_PATH, "count", []),
            *_mix(_SITE_ADDR_PATH),
            *_mix_counts(_SITE_ADDR_PATH),
            ("addresses_by_location", "Addresses inside, by location (spatial links)", ["sp_address_site"],
             "count", [])]


_SITE_CORE = [
    ("site_use", "Site", [], "attr", _DESC),
    ("site_name", "Site name", [], "attr", _SITE_NAME),
    ("land_use", "Land use", [], "attr", _TIER_A),
    ("land_use_detail", "Land use (detail)", [], "attr", _TIER_B),
    ("operator", "Operated by", [], "attr", ["stakeholder"]),
    ("site_status", "Status", [], "attr", ["status"]),
    ("nlud", "National Land Use Database class", [], "attr", ["nlud_groupdescription", "nlud_orderdescription"]),
    ("site_area_m2", "Site area (m²)", [], "attr", _AREA),
    _derive("site_area_ha", "Site area (ha)", "ROUND(site_area_m2 / 10000.0, 2)"),
]
_SITE_BUILDINGS = [
    ("buildings", "Buildings", ["building_primary_site"], "count", []),
    ("building_floor_area_m2", "Floor area of its buildings, est. (m²)", ["building_primary_site"], "agg",
     _agg("SUM", "{a} * COALESCE({f?}, 1)", a=_AREA, f=_FLOORS)),
    ("tallest_building_m", "Tallest building (m)", ["building_primary_site"], "agg", _agg("MAX", "{h}", h=_HEIGHT)),
    ("most_floors", "Most floors", ["building_primary_site"], "agg", _agg("MAX", "{f}", f=_FLOORS)),
    ("building_ages", "Building ages", ["building_primary_site"], "list", _AGE),
    ("buildings_with_solar", "Buildings with solar panels", ["building_primary_site"], "agg",
     _agg("COUNT", "*", "{s} IN ('Present', 'Yes', 'true', '1')", s=_SOLAR)),
    ("south_roof_m2", "South-facing roof (m²)", ["building_primary_site"], "agg", _agg(
        "SUM", "COALESCE({s?}, 0) + COALESCE({se?}, 0) + COALESCE({sw?}, 0)", s=_ROOF_S, se=_ROOF_SE, sw=_ROOF_SW)),
    ("flat_roof_m2", "Flat roof (m²)", ["building_primary_site"], "agg", _agg("SUM", "{r}", r=_ROOF_FLAT)),
    _derive("plot_ratio", "Plot ratio (floor area ÷ site area)",
            "ROUND(building_floor_area_m2 / NULLIF(site_area_m2, 0), 2)"),
]
_SITE_ADDRESSES = [
    ("os_addresses", "Addresses (OS count)", [], "attr", _OS_ADDR_TOTAL),
    ("os_residential", "Residential addresses (OS count)", [], "attr", _OS_ADDR_RES),
    ("os_commercial", "Commercial addresses (OS count)", [], "attr", _OS_ADDR_COM),
    _derive("homes_per_ha", "Homes per hectare",
            "ROUND(COALESCE(os_residential, residential_addresses) / NULLIF(site_area_m2 / 10000.0, 0), 1)"),
    _derive("addresses_per_ha", "Addresses per hectare",
            "ROUND(COALESCE(os_addresses, addresses) / NULLIF(site_area_m2 / 10000.0, 0), 1)"),
    ("address_class_agrees", "Do the addresses agree with the land use?", [], "attr",
     ["address_classificationcorrelation"]),
]

_ANSWERS = {
    "1.": {"subject": A, "title": "Property summary (one row per address)", "colour_by": "building_use",
           "only_in_area": True,      # linked addresses beyond the edge still count in the building columns
           "columns": [
               ("uprn", "UPRN", [], "attr", ["uprn"]),
               ("address", "Address", [], "attr", ["address"]),
               ("postcode", "Postcode", [], "attr", ["postcode"]),
               ("address_class", "Residential or commercial", [], "attr", _CLASS),
               ("address_type", "Address type", [], "attr", ["classification_desc"]),
               ("organisation", "Organisation", [], "attr", ["organisation"]),
               *_building(["building_uprn"]),
               ("addresses_in_building", "Addresses in the building", ["building_uprn", "building_uprn"], "count", []),
               *_mix(["building_uprn", "building_uprn"], "addresses in the building"),
               _derive("floor_area_per_address_m2", "Floor area per address, est. (m²)",
                       "ROUND(floor_area_m2 / NULLIF(addresses_in_building, 0))"),
               _derive("footprint_per_address_m2", "Footprint per address (m²)",
                       "ROUND(footprint_m2 / NULLIF(addresses_in_building, 0))"),
               ("building_parts", "Building parts", ["building_uprn", "building_parts"], "count", []),
               ("site_use", "Site", ["building_uprn", "building_primary_site"], "attr", _DESC),
               ("site_name", "Site name", ["building_uprn", "building_primary_site"], "attr", _SITE_NAME),
               ("land_use", "Land use", ["building_uprn", "building_primary_site"], "attr", _TIER_A),
               ("land_use_detail", "Land use (detail)", ["building_uprn", "building_primary_site"], "attr", _TIER_B),
               ("site_area_m2", "Site area (m²)", ["building_uprn", "building_primary_site"], "attr", _AREA),
               ("buildings_on_site", "Buildings on the site", ["building_uprn", "building_primary_site",
                                                                "building_primary_site"], "count", []),
               ("local_authority", "Local authority (ONS code)", ["building_uprn", "building_parts"], "attr", _LA),
               ("building_osid", "Building ID", ["building_uprn"], "attr", ["osid"]),
               ("site_osid", "Site ID", ["building_uprn", "building_primary_site"], "attr", ["osid"]),
           ]},
    "2.": {"subject": "lus-fts-site", "title": "Site summary (one row per site)", "colour_by": "site_use",
           "columns": [
               *_SITE_CORE,
               *_SITE_BUILDINGS,
               ("building_parts", "Building parts", ["buildingpart_site"], "count", []),
               *_site_addresses(),
               *_SITE_ADDRESSES,
               ("main_address", "Main address", ["site_uprn"], "attr", ["address"]),
               ("entrances", "Entrances", ["sal_site"], "count", []),
               ("entrance_types", "Entrance types", ["sal_site"], "list", ["access_purpose", "accesstype"]),
               ("structures", "Structures", ["structure_site"], "count", []),
               ("structure_types", "What the structures are", ["structure_site"], "list", _DESC),
               ("land_cover", "Land cover", ["land_site"], "list", _DESC),
               *_site_composition(),
               ("local_authority", "Local authority (ONS code)", ["buildingpart_site"], "attr", _LA),
               ("site_osid", "Site ID", [], "attr", ["osid"]),
           ]},
    "3.": {"subject": "lus-fts-siteaccesslocation", "title": "Site entrances (one row per entrance)",
           "colour_by": "access_for",
           "columns": [
               ("access_for", "Access for", [], "attr", ["access_purpose", "accesspurpose", "accesstype"]),
               ("access_by", "Access by", [], "attr", ["access_mode", "accesstype"]),
               ("network", "Joins the", [], "attr", ["accessednetworknodefeaturetype"]),
               ("metres_to_road", "Metres to the road network", [], "attr", ["distancetonetworknode_m"]),
               ("site_use", "Site", ["sal_site"], "attr", _DESC),
               ("site_name", "Site name", ["sal_site"], "attr", _SITE_NAME),
               ("site_area_m2", "Site area (m²)", ["sal_site"], "attr", _AREA),
               ("entrances_to_site", "Entrances to this site", ["sal_site", "sal_site"], "count", []),
               ("emergency_entrances", "Emergency entrances to this site", ["sal_site", "sal_site"], "agg",
                _agg("COUNT", "*", "{p} = 'Emergency'", p=["access_purpose", "accesspurpose"])),
               ("buildings_on_site", "Buildings on the site", ["sal_site", "building_primary_site"], "count", []),
               ("tallest_building_m", "Tallest building on the site (m)", ["sal_site", "building_primary_site"],
                "agg", _agg("MAX", "{h}", h=_HEIGHT)),
               ("most_floors", "Most floors on the site", ["sal_site", "building_primary_site"], "agg",
                _agg("MAX", "{f}", f=_FLOORS)),
               ("building_entrances", "Building entrances on the site",
                ["sal_site", "building_primary_site", "bal_building"], "count", []),
               ("roads_at_entrance", "Roads at the entrance", ["sal_roadnode", "roadlink_nodes"], "list", _DESC),
               ("road_names", "Road names", ["sal_roadnode", "roadlink_nodes"], "list", ["name1_text",
                                                                                          "roadclassificationnumber"]),
               ("road_class", "Road classification", ["sal_roadnode", "roadlink_nodes"], "list",
                ["roadclassification"]),
               ("narrowest_road_m", "Narrowest road width (m)", ["sal_roadnode", "roadlink_nodes"], "agg",
                _agg("MIN", "{w}", w=["roadwidth_minimum", "roadwidth_average"])),
               ("pavement_pct", "Pavement on those roads (%)", ["sal_roadnode", "roadlink_nodes"], "agg",
                _agg("MIN", "{p}", p=["presenceofpavement_overallpercentage"])),
               ("restrictions_nearby", "Restrictions on those roads",
                ["sal_roadnode", "roadlink_nodes", "restriction_roadlink"], "list", ["restriction", "description"]),
               ("barriers_nearby", "Barriers and structures on those roads",
                ["sal_roadnode", "roadlink_nodes", "routingstructure_roadlink"], "list", _DESC),
               ("road_node_osid", "Road Node ID", ["sal_roadnode"], "attr", ["osid"]),
               ("site_osid", "Site ID", ["sal_site"], "attr", ["osid"]),
           ]},
    "4.": {"subject": "bld-fts-building", "title": "Building context (one row per building)",
           "colour_by": "building_use",
           "columns": [
               *_building(),
               ("os_addresses", "Addresses (OS count)", [], "attr", _OS_ADDR_TOTAL),
               ("addresses", "Addresses linked", ["building_uprn"], "count", []),
               *_mix(["building_uprn"]),
               _derive("floor_area_per_address_m2", "Floor area per address, est. (m²)",
                       "ROUND(floor_area_m2 / NULLIF(addresses, 0))"),
               ("building_parts", "Building parts", ["building_parts"], "count", []),
               ("site_use", "Site", ["building_primary_site"], "attr", _DESC),
               ("site_name", "Site name", ["building_primary_site"], "attr", _SITE_NAME),
               ("land_use", "Land use", ["building_primary_site"], "attr", _TIER_A),
               ("postcodes", "Postcode(s)", ["building_uprn"], "list", ["postcode"]),
               ("streets", "Street(s)", ["building_uprn", "address_street"], "list", _STREET),
               ("town", "Town", ["building_uprn", "address_street"], "attr", ["townname1_text", "locality1_text"]),
               ("street_authority", "Street authority", ["building_uprn", "address_street"], "attr",
                ["responsibleauthority_name", "administrativearea1_text"]),
               ("local_authority", "Local authority (ONS code)", ["building_parts"], "attr", _LA),
               ("postcode_area", "Postcode area (by location)", ["sp_building_pcarea"], "attr", ["postcode"]),
               ("building_osid", "Building ID", [], "attr", ["osid"]),
           ]},
    "5.": {"subject": "lus-fts-site", "title": "Education sites (one row per site)", "colour_by": "site_use",
           "columns": [
               *_SITE_CORE,
               *_SITE_BUILDINGS,
               *_site_addresses(),
               *_SITE_ADDRESSES,
               ("main_address", "Main address", ["site_uprn"], "attr", ["address"]),
               ("entrances", "Site entrances", ["sal_site"], "count", []),
               ("entrance_types", "Entrance types", ["sal_site"], "list", ["access_purpose", "accesspurpose"]),
               ("building_entrances", "Building entrances", ["building_primary_site", "bal_building"], "count", []),
               ("roads_giving_access", "Roads giving access", ["sal_site", "sal_roadnode", "roadlink_nodes"], "list",
                _DESC),
               ("road_names", "Road names", ["sal_site", "sal_roadnode", "roadlink_nodes"], "list", ["name1_text"]),
               ("pavement_pct", "Least pavement on those roads (%)", ["sal_site", "sal_roadnode", "roadlink_nodes"],
                "agg", _agg("MIN", "{p}", p=["presenceofpavement_overallpercentage"])),
               *_site_composition(water=None, roads=None),
               _derive("pct_green_space", "% green space (grass + trees)",
                       "ROUND(COALESCE(pct_grass, 0) + COALESCE(pct_trees, 0), 1)"),
               _derive("free_ground_m2", "Open ground not under buildings (m²)",
                       "ROUND(COALESCE(grass_m2, 0) + COALESCE(made_surface_m2, 0))"),
               ("site_osid", "Site ID", [], "attr", ["osid"]),
           ]},
    "6.": {"subject": "trn-ntwk-roadlink", "title": "What each road serves (one row per road link)",
           "colour_by": "sites_served_n",
           "columns": [
               ("road", "Road", [], "attr", _DESC),
               ("road_name", "Road name", [], "attr", ["name1_text"]),
               ("road_number", "Road number", [], "attr", ["roadclassificationnumber"]),
               ("road_class", "Road classification", [], "attr", ["roadclassification"]),
               ("route_hierarchy", "Route hierarchy", [], "attr", ["routehierarchy"]),
               ("length_m", "Length (m)", [], "attr", _LENGTH),
               ("width_m", "Average width (m)", [], "attr", ["roadwidth_average"]),
               ("narrowest_m", "Narrowest (m)", [], "attr", ["roadwidth_minimum"]),
               ("one_way", "Direction of traffic", [], "attr", ["directionality"]),
               ("pavement_pct", "Pavement (% of length)", [], "attr", ["presenceofpavement_overallpercentage"]),
               ("street_lights", "Street lighting", [], "attr", ["presenceofstreetlight_coverage"]),
               ("bus_lane_pct", "Bus lane (% of length)", [], "attr", ["presenceofbuslane_overallpercentage"]),
               ("cycle_lane_pct", "Cycle lane (% of length)", [], "attr", ["presenceofcyclelane_overallpercentage"]),
               ("climb_m", "Climb along it (m)", [], "attr", ["elevationgain_indirection"]),
               ("street", "Street", ["roadlink_street"], "list", _STREET),
               ("street_authority", "Street authority", ["roadlink_street"], "attr",
                ["responsibleauthority_name", "administrativearea1_text"]),
               ("site_entrances", "Site entrances joining it", ["roadlink_nodes", "sal_roadnode"], "count", []),
               ("sites_served_n", "Sites served", ["roadlink_nodes", "sal_roadnode", "sal_site"], "count", []),
               ("sites_served", "Which sites", ["roadlink_nodes", "sal_roadnode", "sal_site"], "list", _DESC),
               ("site_names", "Site names", ["roadlink_nodes", "sal_roadnode", "sal_site"], "list", _SITE_NAME),
               ("buildings_served", "Buildings on those sites",
                ["roadlink_nodes", "sal_roadnode", "sal_site", "building_primary_site"], "count", []),
               ("addresses_served", "Addresses on those sites (OS count)",
                ["roadlink_nodes", "sal_roadnode", "sal_site"], "agg", _agg("SUM", "{n}", n=_OS_ADDR_TOTAL)),
               ("road_osid", "Road Link ID", [], "attr", ["osid"]),
           ]},
    "7.": {"subject": "lus-fts-site", "title": "Utility sites (one row per site)", "colour_by": "site_use",
           "columns": [
               *_SITE_CORE,
               ("structures", "Structures", ["structure_site"], "count", []),
               ("structure_types", "What the structures are", ["structure_site"], "list", _DESC),
               ("structure_area_m2", "Area of structures (m²)", ["structure_site"], "agg",
                _agg("SUM", "{a}", a=_AREA)),
               ("structure_points", "Structure points (by location)", ["sp_structurepoint_site"], "count", []),
               ("structure_point_types", "What the structure points are", ["sp_structurepoint_site"], "list", _DESC),
               *_SITE_BUILDINGS,
               ("main_address", "Main address", ["site_uprn"], "attr", ["address"]),
               *_site_composition(parts=None, water=None, roads=None),
               ("site_osid", "Site ID", [], "attr", ["osid"]),
           ]},
    "8.": {"subject": "lus-fts-site", "title": "Sites and what's on them (one row per site)", "colour_by": "site_use",
           "columns": [
               *_SITE_CORE,
               *_SITE_BUILDINGS,
               ("main_building", "Main building ID", [], "attr", ["mainbuildingid"]),
               ("building_footprint_m2", "Footprint of its buildings (m²)", ["building_primary_site"], "agg",
                _agg("SUM", "{a}", a=_AREA)),
               _derive("pct_built_over", "% of the site built over",
                       "ROUND(100.0 * building_footprint_m2 / NULLIF(site_area_m2, 0), 1)"),
               *_site_addresses(),
               *_SITE_ADDRESSES,
               _derive("floor_area_per_address_m2", "Floor area per address, est. (m²)",
                       "ROUND(building_floor_area_m2 / NULLIF(COALESCE(os_addresses, addresses), 0))"),
               ("address_types", "Address types (detail)", _SITE_ADDR_PATH, "list", ["classification_desc"]),
               ("main_address", "Main address", ["site_uprn"], "attr", ["address"]),
               ("site_osid", "Site ID", [], "attr", ["osid"]),
           ]},
    "9.": {"subject": "lus-fts-site", "title": "Land use (one row per site)", "colour_by": "land_use",
           "columns": [
               *_SITE_CORE,
               ("address_agrees", "Do the addresses agree with the land use?", [], "attr",
                ["address_classificationcorrelation"]),
               ("address_land_use", "Land use from addresses", [], "attr", ["address_primarydescription"]),
               ("building_parts", "Building parts", ["buildingpart_site"], "count", []),
               ("land_areas", "Land areas", ["land_site"], "count", []),
               ("land_cover", "Land cover", ["land_site"], "list", _DESC),
               ("water_areas", "Water areas", ["water_site"], "count", []),
               ("structures", "Structures", ["structure_site"], "count", []),
               ("structure_area_m2", "Area of structures (m²)", ["structure_site"], "agg",
                _agg("SUM", "{a}", a=_AREA)),
               *_site_composition(),
               _derive("pct_green_space", "% green space (grass + trees)",
                       "ROUND(COALESCE(pct_grass, 0) + COALESCE(pct_trees, 0), 1)"),
               _derive("pct_sealed", "% sealed surface (buildings + paved + roads)",
                       "ROUND(COALESCE(pct_buildings, 0) + COALESCE(pct_made_surface, 0) + "
                       "COALESCE(pct_roads_paths, 0), 1)"),
               ("local_authority", "Local authority (ONS code)", ["land_site"], "attr", _LA),
               ("site_osid", "Site ID", [], "attr", ["osid"]),
           ]},
}

for _r in RECIPES:
    _r["answer"] = _ANSWERS.get(_r["name"][:2])


# ---------------------------------------------------------------------------------------------- showcase picks
# Quick picks built to show off what OS NGD holds: each gives one answer layer with the address mix
# (how many residential / commercial / mixed-use, and the %) wherever addresses can be reached.
HEALTH_SITES = ["Hospital", "Hospice", "Health Centre", "Medical Care Site", "Medical Care Accommodation",
                "Social Care Services Site"]
EMERGENCY_SITES = ["Ambulance Station", "Fire Station", "Police Station", "Ambulance And Fire Station",
                   "Ambulance And Police Station", "Fire Station And Police Station",
                   "Ambulance, Fire And Police Station", "Police Headquarters"]
COMMUNITY_SITES = ["Library", "Community Meeting Place", "Community Services", "Multi-Purpose Community Site",
                   "Leisure Or Sports Centre", "Place Of Worship", "Church"]
COMMUNITY_FACILITIES = EDUCATION_SITES + HEALTH_SITES + EMERGENCY_SITES + COMMUNITY_SITES + UTILITY_SITES


def _sql_list(values):
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def _character(total="addresses"):
    """A one-phrase summary of the mix, for colouring the map."""
    return _derive("character", "Character", (
        f"CASE WHEN COALESCE({total}, 0) = 0 THEN 'No addresses' "
        "WHEN pct_residential >= 80 THEN 'Mainly residential' "
        "WHEN pct_commercial >= 80 THEN 'Mainly commercial' "
        "WHEN COALESCE(pct_residential, 0) >= 50 THEN 'Mixed - mostly residential' "
        "WHEN COALESCE(pct_commercial, 0) >= 50 THEN 'Mixed - mostly commercial' ELSE 'Mixed' END"))


def _address_block(path, area_col=None, floor_col=None):
    """Addresses along ``path``: count, mix (text, %, numbers), character, and densities."""
    cols = [("addresses", "Addresses", path, "count", []), *_mix(path), *_mix_counts(path), _character(),
            ("address_types", "Address types (detail)", path, "list", ["classification_desc"])]
    if area_col:
        cols += [_derive("homes_per_ha", "Homes per hectare",
                         f"ROUND(residential_addresses / NULLIF({area_col} / 10000.0, 0), 1)"),
                 _derive("addresses_per_ha", "Addresses per hectare",
                         f"ROUND(addresses / NULLIF({area_col} / 10000.0, 0), 1)")]
    if floor_col:
        cols.append(_derive("floor_area_per_address_m2", "Floor area per address, est. (m²)",
                            f"ROUND({floor_col} / NULLIF(addresses, 0))"))
    return cols


_ROOF_ASPECTS = [("north", "N"), ("northeast", "NE"), ("east", "E"), ("southeast", "SE"), ("south", "S"),
                 ("southwest", "SW"), ("west", "W"), ("northwest", "NW")]

_SHOWCASE_ANSWERS = {
    "site_mix": {"subject": "lus-fts-site", "title": "Site address mix (one row per site)", "colour_by": "character",
                 "columns": [
                     *_SITE_CORE,
                     ("buildings", "Buildings", ["building_primary_site"], "count", []),
                     ("building_floor_area_m2", "Floor area of its buildings, est. (m²)", ["building_primary_site"],
                      "agg", _agg("SUM", "{a} * COALESCE({f?}, 1)", a=_AREA, f=_FLOORS)),
                     *_address_block(_SITE_ADDR_PATH, "site_area_m2", "building_floor_area_m2"),
                     ("os_addresses", "Addresses (OS's own count on the site)", [], "attr", _OS_ADDR_TOTAL),
                     ("address_class_agrees", "Do the addresses agree with the land use?", [], "attr",
                      ["address_classificationcorrelation"]),
                     ("main_address", "Main address", ["site_uprn"], "attr", ["address"]),
                     ("main_building", "Main building", ["site_mainbuilding"], "attr", _BUSE),
                     ("postcodes", "Postcode(s)", _SITE_ADDR_PATH, "list", ["postcode"]),
                     ("site_osid", "Site ID", [], "attr", ["osid"]),
                 ]},
    "housing": {"subject": "bld-fts-building", "title": "Housing stock (one row per building)",
                "colour_by": "connectivity",
                "columns": [
                    *_building(),
                    ("building_parts", "Building parts", ["building_parts"], "count", []),
                    *_address_block(["building_uprn"], floor_col="floor_area_m2"),
                    _derive("floor_area_per_home_m2", "Floor area per home, est. (m²)",
                            "ROUND(floor_area_m2 / NULLIF(residential_addresses, 0))"),
                    ("os_addresses", "Addresses (OS's own count)", [], "attr", _OS_ADDR_TOTAL),
                    ("postcodes", "Postcode(s)", ["building_uprn"], "list", ["postcode"]),
                    ("streets", "Street(s)", ["building_uprn", "address_street"], "list", _STREET),
                    ("site_use", "Site", ["building_primary_site"], "attr", _DESC),
                    ("land_use", "Land use", ["building_primary_site"], "attr", _TIER_A),
                    ("local_authority", "Local authority (ONS code)", ["building_parts"], "attr", _LA),
                    ("building_osid", "Building ID", [], "attr", ["osid"]),
                ]},
    "street": {"subject": "trn-ntwk-street", "title": "Street profile (one row per street / USRN)",
               "colour_by": "character",
               "columns": [
                   ("street", "Street", [], "attr", _STREET),
                   ("usrn", "USRN", [], "attr", ["usrn"]),
                   ("town", "Town", [], "attr", ["townname1_text", "locality1_text"]),
                   ("street_type", "Street type", [], "attr", ["streettype", "description"]),
                   ("operational_state", "Operational state", [], "attr", ["operationalstate"]),
                   ("street_authority", "Street authority", [], "attr",
                    ["responsibleauthority_name", "administrativearea1_text"]),
                   *_address_block(["address_street"]),
                   ("buildings", "Buildings with an address on it", ["address_street", "building_uprn"], "count", []),
                   ("building_ages", "Building ages", ["address_street", "building_uprn"], "list", _AGE),
                   ("house_types", "Detached / semi / terrace", ["address_street", "building_uprn"], "list",
                    _CONNECT),
                   ("road_links", "Road links", ["roadlink_street"], "count", []),
                   ("road_length_m", "Length of road (m)", ["roadlink_street"], "agg", _agg("SUM", "{l}", l=_LENGTH)),
                   _derive("addresses_per_100m", "Addresses per 100 m of road",
                           "ROUND(100.0 * addresses / NULLIF(road_length_m, 0), 1)"),
                   ("road_class", "Road classification", ["roadlink_street"], "list", ["roadclassification"]),
                   ("pavement_pct", "Least pavement (% of length)", ["roadlink_street"], "agg",
                    _agg("MIN", "{p}", p=["presenceofpavement_overallpercentage"])),
                   ("maintained", "Maintenance", ["maintenancearea_street"], "list", ["maintenanceresponsibility"]),
                   ("maintained_line", "Maintenance (lines)", ["maintenanceline_street"], "list",
                    ["maintenanceresponsibility"]),
                   ("dedication", "Highway dedication", ["highwaydedication_street"], "list", _DESC),
                   ("designations", "Special designations", ["specialdesignationline_street"], "list",
                    ["designation"]),
                   ("designation_areas", "Special designation areas", ["specialdesignationarea_street"], "list",
                    ["designation"]),
                   ("restrictions", "Restrictions on its roads", ["roadlink_street", "restriction_roadlink"], "list",
                    ["restriction"]),
                   ("street_osid", "Street ID", [], "attr", ["osid"]),
               ]},
    "postcode": {"subject": "asu-gbpcd-postcodeunitarea", "title": "Postcode profile (one row per postcode)",
                 "colour_by": "character",
                 "columns": [
                     ("postcode", "Postcode", [], "attr", ["postcode"]),
                     ("postcode_area_m2", "Area (m²)", [], "attr", _AREA),
                     *_address_block(["address_pcarea"], "postcode_area_m2"),
                     ("buildings", "Buildings", ["address_pcarea", "building_uprn"], "count", []),
                     ("building_ages", "Building ages", ["address_pcarea", "building_uprn"], "list", _AGE),
                     ("house_types", "Detached / semi / terrace", ["address_pcarea", "building_uprn"], "list",
                      _CONNECT),
                     ("tallest_m", "Tallest building (m)", ["address_pcarea", "building_uprn"], "agg",
                      _agg("MAX", "{h}", h=_HEIGHT)),
                     ("floor_area_m2", "Floor area of its buildings, est. (m²)", ["address_pcarea", "building_uprn"],
                      "agg", _agg("SUM", "{a} * COALESCE({f?}, 1)", a=_AREA, f=_FLOORS)),
                     _derive("floor_area_per_address_m2", "Floor area per address, est. (m²)",
                             "ROUND(floor_area_m2 / NULLIF(addresses, 0))"),
                     ("sites", "Sites", ["address_pcarea", "building_uprn", "building_primary_site"], "list", _DESC),
                     ("streets", "Street(s)", ["address_pcarea", "address_street"], "list", _STREET),
                     ("positional_accuracy", "Positional accuracy", ["pcpoint_pcarea"], "attr",
                      ["inputaddressaccuracy"]),
                 ]},
    "solar": {"subject": "bld-fts-building", "title": "Solar and roof potential (one row per building)",
              "colour_by": "solar_potential",
              "columns": [
                  ("building_use", "Building use", [], "attr", _BUSE),
                  ("building_type", "Building", [], "attr", _DESC),
                  ("connectivity", "Detached / semi / terrace", [], "attr", _CONNECT),
                  ("building_age", "Built (period)", [], "attr", _AGE),
                  ("floors", "Floors", [], "attr", _FLOORS),
                  ("height_m", "Height (m)", [], "attr", _HEIGHT),
                  ("footprint_m2", "Footprint (m²)", [], "attr", _AREA),
                  ("roof_shape", "Roof shape", [], "attr", _ROOF_SHAPE),
                  ("roof_material", "Roof material", [], "attr", _ROOF),
                  ("solar_panels", "Solar panels already", [], "attr", _SOLAR),
                  ("green_roof", "Green roof", [], "attr", _GREEN_ROOF),
                  *[(f"roof_{k}_m2", f"Roof facing {a} (m²)", [], "attr", [f"roofshapeaspect_areafacing{k}_m2"])
                    for k, a in _ROOF_ASPECTS],
                  ("flat_roof_m2", "Flat roof (m²)", [], "attr", _ROOF_FLAT),
                  _derive("south_roof_m2", "South-facing roof, S + SE + SW (m²)",
                          "ROUND(COALESCE(roof_south_m2, 0) + COALESCE(roof_southeast_m2, 0) + "
                          "COALESCE(roof_southwest_m2, 0), 1)"),
                  _derive("usable_roof_m2", "Usable for solar, south + flat (m²)",
                          "ROUND(COALESCE(roof_south_m2, 0) + COALESCE(roof_southeast_m2, 0) + "
                          "COALESCE(roof_southwest_m2, 0) + COALESCE(flat_roof_m2, 0), 1)"),
                  _derive("pct_roof_usable", "Usable roof as % of footprint",
                          "ROUND(100.0 * (COALESCE(roof_south_m2, 0) + COALESCE(roof_southeast_m2, 0) + "
                          "COALESCE(roof_southwest_m2, 0) + COALESCE(flat_roof_m2, 0)) / NULLIF(footprint_m2, 0), 1)"),
                  _derive("solar_potential", "Solar potential", (
                      "CASE WHEN solar_panels IN ('Present', 'Yes', 'true', '1') THEN 'Already has panels' "
                      "WHEN roof_shape IS NULL AND flat_roof_m2 IS NULL THEN 'No roof data' "
                      "WHEN COALESCE(roof_south_m2, 0) + COALESCE(roof_southeast_m2, 0) + COALESCE(roof_southwest_m2, 0) "
                      "+ COALESCE(flat_roof_m2, 0) >= 40 THEN 'High' "
                      "WHEN COALESCE(roof_south_m2, 0) + COALESCE(roof_southeast_m2, 0) + COALESCE(roof_southwest_m2, 0) "
                      "+ COALESCE(flat_roof_m2, 0) >= 15 THEN 'Medium' ELSE 'Low' END")),
                  ("addresses", "Addresses that would benefit", ["building_uprn"], "count", []),
                  *_mix(["building_uprn"]),
                  *_mix_counts(["building_uprn"]),
                  _derive("usable_roof_per_address_m2", "Usable roof per address (m²)",
                          "ROUND(usable_roof_m2 / NULLIF(addresses, 0), 1)"),
                  ("site_use", "Site", ["building_primary_site"], "attr", _DESC),
                  ("building_osid", "Building ID", [], "attr", ["osid"]),
              ]},
    "green": {"subject": "lus-fts-site", "title": "Green and sealed land (one row per site)",
              "colour_by": "pct_green_space",
              "columns": [
                  *_SITE_CORE,
                  *_site_composition(),
                  _derive("pct_green_space", "% green space (grass + trees + gardens)",
                          "ROUND(COALESCE(pct_grass, 0) + COALESCE(pct_trees, 0) + COALESCE(pct_gardens, 0), 1)"),
                  _derive("pct_sealed", "% sealed surface (buildings + paved + roads)",
                          "ROUND(COALESCE(pct_buildings, 0) + COALESCE(pct_made_surface, 0) + "
                          "COALESCE(pct_roads_paths, 0), 1)"),
                  _derive("green_m2_per_home", "Green space per home (m²)",
                          "ROUND((COALESCE(grass_m2, 0) + COALESCE(trees_m2, 0) + COALESCE(gardens_m2, 0)) / "
                          "NULLIF(residential_addresses, 0))"),
                  ("land_cover", "Land cover", ["land_site"], "list", _DESC),
                  ("buildings", "Buildings", ["building_primary_site"], "count", []),
                  *_address_block(_SITE_ADDR_PATH, "site_area_m2"),
                  ("local_authority", "Local authority (ONS code)", ["land_site"], "attr", _LA),
                  ("site_osid", "Site ID", [], "attr", ["osid"]),
              ]},
    "access": {"subject": "lus-fts-siteaccesslocation", "title": "Site access and network (one row per entrance)",
               "colour_by": "access_for",
               "columns": [
                   ("access_for", "Access for", [], "attr", ["access_purpose", "accesspurpose"]),
                   ("access_type", "Access type", [], "attr", ["accesstype", "description"]),
                   ("distance_to_network_m", "Distance to the network (m)", [], "attr", ["distancetonetworknode_m"]),
                   ("network", "Joins the", [], "attr", ["accessednetworknodefeaturetype"]),
                   ("site_use", "Site", ["sal_site"], "attr", _DESC),
                   ("site_name", "Site name", ["sal_site"], "attr", _SITE_NAME),
                   ("entrances_to_site", "Entrances to this site", ["sal_site", "sal_site"], "count", []),
                   ("buildings_on_site", "Buildings on the site", ["sal_site", "building_primary_site"], "count", []),
                   ("addresses_served", "Addresses on the site", ["sal_site", *_SITE_ADDR_PATH], "count", []),
                   *_mix(["sal_site", *_SITE_ADDR_PATH], "addresses on the site"),
                   *_mix_counts(["sal_site", *_SITE_ADDR_PATH]),
                   ("roads_at_entrance", "Roads at the entrance", ["sal_roadnode", "roadlink_nodes"], "list", _DESC),
                   ("road_names", "Road names", ["sal_roadnode", "roadlink_nodes"], "list",
                    ["name1_text", "roadclassificationnumber"]),
                   ("road_class", "Road classification", ["sal_roadnode", "roadlink_nodes"], "list",
                    ["roadclassification"]),
                   ("narrowest_road_m", "Narrowest road width (m)", ["sal_roadnode", "roadlink_nodes"], "agg",
                    _agg("MIN", "{w}", w=["roadwidth_minimum", "roadwidth_average"])),
                   ("dedication", "Highway dedication", ["sal_roadnode", "roadlink_nodes",
                                                         "highwaydedication_roadlink"], "list", _DESC),
                   ("restrictions", "Restrictions on those roads",
                    ["sal_roadnode", "roadlink_nodes", "restriction_roadlink"], "list", ["restriction"]),
                   ("barriers", "Barriers and structures on those roads",
                    ["sal_roadnode", "roadlink_nodes", "routingstructure_roadlink"], "list", _DESC),
                   ("paths_at_entrance", "Paths at the entrance", ["sal_pathnode", "pathlink_nodes"], "list", _DESC),
                   ("site_osid", "Site ID", ["sal_site"], "attr", ["osid"]),
               ]},
    "community": {"subject": "lus-fts-site", "title": "Community facilities (one row per site)",
                  "colour_by": "facility",
                  "columns": [
                      _derive("facility", "Facility", (
                          f"CASE WHEN site_use IN ({_sql_list(EDUCATION_SITES)}) THEN 'Education' "
                          f"WHEN site_use IN ({_sql_list(HEALTH_SITES)}) THEN 'Health and care' "
                          f"WHEN site_use IN ({_sql_list(EMERGENCY_SITES)}) THEN 'Emergency services' "
                          f"WHEN site_use IN ({_sql_list(UTILITY_SITES)}) THEN 'Utility' "
                          "ELSE 'Community' END")),
                      *_SITE_CORE,
                      *_SITE_BUILDINGS,
                      *_address_block(_SITE_ADDR_PATH, "site_area_m2", "building_floor_area_m2"),
                      ("main_address", "Main address", ["site_uprn"], "attr", ["address"]),
                      ("entrances", "Site entrances", ["sal_site"], "count", []),
                      ("entrance_types", "Entrance types", ["sal_site"], "list", ["access_purpose", "accesspurpose"]),
                      ("roads_giving_access", "Roads giving access", ["sal_site", "sal_roadnode", "roadlink_nodes"],
                       "list", _DESC),
                      ("road_names", "Road names", ["sal_site", "sal_roadnode", "roadlink_nodes"], "list",
                       ["name1_text"]),
                      ("site_osid", "Site ID", [], "attr", ["osid"]),
                  ]},
}

SHOWCASE_RECIPES = [
    {"name": "Site address mix", "key": "site_mix",
     "question": "Which sites are residential, commercial or mixed - and in what proportion?",
     "path": "Site ← Building → Address (UPRN)",
     "answers": "For every site: how many addresses, how many residential / commercial / mixed use and the %, "
                "homes per hectare, floor area per address, its main address and main building.",
     "types": ["lus-fts-site", "bld-fts-building", A],
     "links": ["building_primary_site", "building_uprn", "site_uprn", "site_mainbuilding"],
     "note": "Colour the map by 'Character' (mainly residential / commercial / mixed). Addresses come through "
             "the site's buildings - OS's own cross-references."},
    {"name": "Housing stock profile", "key": "housing",
     "question": "What are the buildings like - age, type, size - and who lives or works in them?",
     "path": "Building → Address, Building Part, Site, Street",
     "answers": "Detached / semi / terrace, age, floors, height, construction, floor area per home, how many "
                "addresses and their residential / commercial mix.",
     "types": ["bld-fts-building", "bld-fts-buildingpart", A, "lus-fts-site", "trn-ntwk-street"],
     "links": ["building_uprn", "building_parts", "building_primary_site", "address_street"],
     "note": "Floor area is estimated as footprint × floors."},
    {"name": "Street profile (USRN)", "key": "street",
     "question": "What's on each street, and who looks after it?",
     "path": "Street (USRN) ← Address → Building; Street ← Road Link; Street ← highway records",
     "answers": "Addresses and their mix per street, buildings and their ages, road length and class, "
                "addresses per 100 m, maintenance responsibility, highway dedication, designations and "
                "restrictions.",
     "types": ["trn-ntwk-street", A, "bld-fts-building", "trn-ntwk-roadlink", "trn-rami-maintenancearea",
               "trn-rami-maintenanceline", "trn-rami-highwaydedication", "trn-rami-specialdesignationline",
               "trn-rami-specialdesignationarea", "trn-rami-restriction"],
     "links": ["address_street", "building_uprn", "roadlink_street", "maintenancearea_street",
               "maintenanceline_street", "highwaydedication_street", "specialdesignationline_street",
               "specialdesignationarea_street", "restriction_roadlink"],
     "note": "Addresses reach a street through their USRN (OS Places LPI records - added automatically)."},
    {"name": "Postcode profile", "key": "postcode",
     "question": "What is each postcode like?",
     "path": "Postcode ← Address → Building → Site",
     "answers": "Addresses and their mix per postcode, homes per hectare, building ages and types, floor area "
                "per address, the sites and streets in it.",
     "types": ["asu-gbpcd-postcodeunitarea", "asu-gbpcd-postcodeunitpoint", A, "bld-fts-building",
               "lus-fts-site", "trn-ntwk-street"],
     "links": ["address_pcarea", "pcpoint_pcarea", "building_uprn", "building_primary_site", "address_street"],
     "note": "Postcodes are postal groupings, not property keys - they can change."},
    {"name": "Solar and roof potential", "key": "solar",
     "question": "Which roofs could take solar panels?",
     "path": "Building (roof shape and aspect) → Address",
     "answers": "Roof area facing each direction, flat roof, panels already fitted, a High / Medium / Low "
                "potential, and the addresses (residential / commercial) that would benefit.",
     "types": ["bld-fts-building", A, "lus-fts-site"],
     "links": ["building_uprn", "building_primary_site"],
     "note": "Roof aspect areas come from OS's Building attributes; 'usable' = south, south-east, south-west "
             "and flat. High ≥ 40 m², Medium ≥ 15 m²."},
    {"name": "Green and sealed land", "key": "green",
     "question": "How green is each site, and how much is paved over?",
     "path": "Land, Building Part, Water, Road/Track/Path → Site",
     "answers": "m² and % of each site under grass, trees, gardens, made surface, buildings, water and roads; "
                "% green, % sealed, green space per home and the address mix.",
     "types": ["lus-fts-site", "lnd-fts-land", "bld-fts-buildingpart", "wtr-fts-water", "trn-fts-roadtrackorpath",
               "bld-fts-building", A],
     "links": ["land_site", "buildingpart_site", "water_site", "roadtrackorpath_site", "building_primary_site",
               "building_uprn"],
     "note": "Every topographic area records the site it lies in, so composition needs no spatial links."},
    {"name": "Site access and network", "key": "access",
     "question": "How do people and vehicles get into each site?",
     "path": "Site Access Location → Site; → Road Node → Road Link → highway records; → Path Node",
     "answers": "Each entrance: who it's for, how far from the network, the roads and paths it joins, their "
                "width, dedication, restrictions and barriers, and the addresses on the site it serves.",
     "types": ["lus-fts-siteaccesslocation", "lus-fts-site", "trn-ntwk-roadnode", "trn-ntwk-roadlink",
               "trn-ntwk-pathnode", "trn-ntwk-pathlink", "trn-rami-highwaydedication", "trn-rami-restriction",
               "trn-rami-routingstructure", "bld-fts-building", A],
     "links": ["sal_site", "sal_roadnode", "sal_pathnode", "roadlink_nodes", "pathlink_nodes",
               "highwaydedication_roadlink", "restriction_roadlink", "routingstructure_roadlink",
               "building_primary_site", "building_uprn"]},
    {"name": "Community facilities", "key": "community",
     "question": "Where are the schools, health, emergency, community and utility sites - and what's on them?",
     "path": "Site (filtered) ← Building → Address; Site ← Site Access Location → roads",
     "answers": "Each facility: its type, buildings, floor area, address mix, entrances and the roads that "
                "serve it.",
     "types": ["lus-fts-site", "bld-fts-building", A, "lus-fts-siteaccesslocation", "trn-ntwk-roadnode",
               "trn-ntwk-roadlink"],
     "links": ["building_primary_site", "building_uprn", "site_uprn", "sal_site", "sal_roadnode", "roadlink_nodes"],
     "filters": {"lus-fts-site": COMMUNITY_FACILITIES},
     "note": "Sites are narrowed to community facilities - double-click Site to change that."},
]
for _r in SHOWCASE_RECIPES:
    _r["answer"] = _SHOWCASE_ANSWERS[_r["key"]]


def path_types(subject, path):
    """The feature type reached at each step of an answer column's path (and which way each link is used)."""
    cur, out = subject, []
    for lid in path:
        lk = LINK_BY_ID[lid]
        if lk["holder"] == cur:
            out.append((lk, "out"))
            cur = lk["target"]
        elif lk["target"] == cur:
            out.append((lk, "in"))
            cur = lk["holder"]
        else:
            raise ValueError(f"{lid} doesn't touch {cur}")
    return out, cur


# for data engineers: whole networks and record families
ENGINEER_RECIPES = [
    {"name": "Road network with streets and routing information",
     "types": ["trn-ntwk-roadlink", "trn-ntwk-roadnode", "trn-ntwk-road", "trn-ntwk-street", "trn-ntwk-roadjunction",
               "trn-rami-restriction", "trn-rami-routinghazard", "trn-rami-routingstructure",
               "trn-rami-averageandindicativespeed"],
     "links": ["roadlink_nodes", "roadlink_road", "roadlink_street", "roadnode_junction", "restriction_roadlink",
               "routinghazard_roadlink", "routingstructure_roadlink", "averageandindicativespeed_roadlink",
               "restriction_roadnode", "routinghazard_roadnode", "routingstructure_roadnode"]},
    {"name": "Path network (with connections to roads)",
     "types": ["trn-ntwk-pathlink", "trn-ntwk-pathnode", "trn-ntwk-path", "trn-ntwk-connectinglink",
               "trn-ntwk-connectingnode", "trn-ntwk-roadnode", "trn-ntwk-street"],
     "links": ["pathlink_nodes", "pathlink_path", "pathlink_street", "connectinglink_nodes", "connectinglink_pathnode",
               "connectingnode_roadnode"]},
    {"name": "Street works and highway records (USRN)",
     "types": ["trn-ntwk-street", "trn-ntwk-roadlink", "trn-rami-highwaydedication", "trn-rami-maintenancearea",
               "trn-rami-maintenanceline", "trn-rami-reinstatementline", "trn-rami-specialdesignationline"],
     "links": ["roadlink_street", "highwaydedication_street", "maintenancearea_street", "maintenanceline_street",
               "reinstatementline_street", "specialdesignationline_street"]},
    {"name": "Water network", "types": ["wtr-ntwk-waterlink", "wtr-ntwk-waternode", "wtr-ntwk-waterlinkset",
                                        "wtr-fts-water"],
     "links": ["waterlink_nodes", "waterlink_set"]},
    {"name": "Rail network", "types": ["trn-ntwk-railwaylink", "trn-ntwk-railwaynode", "trn-ntwk-railwaylinkset",
                                       "trn-fts-rail"],
     "links": ["railwaylink_nodes", "railwaylink_set"]},
]


def find_path(start, end, spatial=False):
    """The shortest chain of links between two feature types (either direction along each link), as
    [(link, direction)] where direction is 'out' (start of the step holds it) or 'in'. [] if start == end,
    None if there's no chain."""
    from collections import deque
    if start == end:
        return []
    prev = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        for lk in links_for(cur):
            if lk["kind"] == "spatial" and not spatial:
                continue
            if not (TYPES[lk["holder"]]["available"] and TYPES[lk["target"]]["available"]):
                continue
            nxt, side = (lk["target"], "out") if lk["holder"] == cur else (lk["holder"], "in")
            if nxt in prev:
                continue
            prev[nxt] = (cur, lk, side)
            if nxt == end:
                steps = []
                node = end
                while prev[node] is not None:
                    p, l, sd = prev[node]
                    steps.append((l, sd))
                    node = p
                return list(reversed(steps))
            q.append(nxt)
    return None


def describe_path(start, steps):
    """'Address → is in Building (Building → its addresses (UPRNs)) → …' as plain-English lines."""
    lines, cur = [noun(start)], start
    for lk, side in steps:
        nxt = lk["target"] if side == "out" else lk["holder"]
        why = lk["fwd"] if side == "out" else lk["back"]
        kind = "stored ID" if lk["kind"] == "id" else "worked out from location"
        lines.append(f"→ {noun(nxt)}  ({noun(cur)}: {why} - {kind})")
        cur = nxt
    return lines


# ---------------------------------------------------------------------------------------------- matching
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def norm(value, key="osid"):
    """A key as compared between feature types: OSIDs lower-cased, UPRN/USRN as plain integers (no leading
    zeros, no '.0'), postcodes upper-cased without spaces. None for blanks."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("none", "null", "nan"):
        return None
    if key in ("uprn", "usrn"):
        s = re.sub(r"\.0+$", "", s)
        digits = re.sub(r"\D", "", s)
        return digits.lstrip("0") or (digits or None)
    if key == "postcode":
        return re.sub(r"\s+", "", s).upper()
    return s.lower()


def _maybe_json(v):
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def values_of(raw, sub=(), key="osid", match=None):
    """Every identifier in one attribute value: a scalar, a list, a JSON-encoded list, or a list of objects
    (an inline cross-reference table - read ``sub`` keys, else any key that looks like the identifier)."""
    raw = _maybe_json(raw)
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for it in items:
        it = _maybe_json(it)
        if isinstance(it, dict):
            # a shared reference table (e.g. Restriction Network Reference lists Road Links AND Road Nodes):
            # keep only the rows for this link's target
            if match and any(k in it and str(it[k]).lower() not in [m.lower() for m in v] for k, v in match.items()):
                continue
            val = None
            for s in sub:
                if it.get(s) not in (None, ""):
                    val = it[s]
                    break
            if val is None:     # no listed key: the object's identifier-looking key ('uprn', 'usrn', '...id')
                for k, v in it.items():
                    kl = k.lower()
                    if v in (None, "") or "date" in kl:
                        continue
                    if (key != "osid" and key in kl) or (key == "osid" and (kl.endswith("id") or
                                                                            _UUID.match(str(v)))):
                        val = v
                        break
            if val is not None:
                n = norm(val, key)
                if n:
                    out.append(n)
        elif isinstance(it, list):
            out.extend(values_of(it, sub, key, match))
        else:
            n = norm(it, key)
            if n:
                out.append(n)
    return out


def _stem(base):
    return short(base).replace("_", "")


_ALL_STEMS = None


def _heuristic_fields(props, target, key, holder=None):
    """Attribute names that, by their name, probably hold a reference to ``target`` - for when the schema's
    field name differs from the specification's (e.g. a renamed ``..._id``). A name that belongs to a more
    specific feature type (``buildingpartreference`` is Building Part, not Building) or that another link
    of the same holder already claims is never guessed."""
    global _ALL_STEMS
    if _ALL_STEMS is None:
        _ALL_STEMS = {_stem(t) for t in TYPES if TYPES[t]["available"]}
    stem = _stem(target)
    longer = [st for st in _ALL_STEMS if stem in st and st != stem]
    claimed = {f for lk in LINKS if lk["holder"] == holder and lk["target"] != target for f in lk["fields"]}
    out = []
    for name in props:
        n = name.lower().replace("_", "")
        if n in ("osid", "toid", "versionid", "versiondate", "theme", "description") or name in claimed:
            continue
        if any(st in n for st in longer):
            continue
        if key in ("uprn", "usrn", "postcode"):
            if key in n:
                out.append(name)
        elif stem in n and ("id" in n or "reference" in n or "node" in n):
            out.append(name)
    return out


def detect_field(link, sample, reverse=False):
    """Works out which attribute(s) carry ``link`` in real data. ``sample``: a few property dicts of the
    holder (or, with ``reverse``, the target). Returns (fields, how) - ``how`` is 'schema' (a name from the
    register), 'guess' (found by name), or None with no fields if the link isn't in this data."""
    names = link["rev"] if reverse else link["fields"]
    key = "osid" if reverse else link["key"]
    sub = link["rev_sub"] if reverse else link["sub"]
    present = set()
    for p in sample:
        for name in names:
            if name in p and values_of(p[name], sub, key, None if reverse else link.get("match")):
                present.add(name)
    if present:
        found = [n for n in names if n in present]
        return (found if link["all_fields"] else found[:1]), "schema"
    if reverse or not sample:
        return [], None
    counts = {}
    for p in sample:
        for name in _heuristic_fields(p, link["target"], key, link["holder"]):
            if values_of(p[name], sub, key):
                counts[name] = counts.get(name, 0) + 1
    if not counts:
        return [], None
    best = sorted(counts, key=lambda n: (-counts[n], n))
    return (best if link["all_fields"] else best[:1]), "guess"


def pairs_for(link, holders, targets=None, fields=None, reverse_fields=None):
    """The links found in the data, as ``[(holder key, target key, via field)]``.

    ``holders`` / ``targets``: ``{own key: properties}`` for each feature type. Forward links read
    ``fields`` on each holder; reversed ones (stored on the target) read ``reverse_fields`` on each
    target. Duplicate pairs (same holder, target and field) are dropped."""
    out, seen = [], set()
    when = link.get("when") or {}

    def applies(props):     # e.g. only Site Access Locations whose node is on the Road Network
        return all(k not in props or props[k] in (None, "") or str(props[k]).lower() in [v.lower() for v in vals]
                   for k, vals in when.items())
    if fields:
        for hk, props in holders.items():
            if when and not applies(props):
                continue
            for f in fields:
                for tk in values_of(props.get(f), link["sub"], link["key"], link.get("match")):
                    if (hk, tk, f) not in seen and not (link["holder"] == link["target"] and hk == tk):
                        seen.add((hk, tk, f))
                        out.append((hk, tk, f))
    if reverse_fields and targets:
        for tk, props in targets.items():
            for f in reverse_fields:
                for hk in values_of(props.get(f), link["rev_sub"], "osid"):
                    if (hk, tk, f) not in seen:
                        seen.add((hk, tk, f))
                        out.append((hk, tk, f))
    return out


def key_of(props, key="osid"):
    if key == "osid":
        return norm(props.get("osid") or props.get("OSID") or props.get("id"), "osid")
    return norm(props.get(key), key)


def cql_in(attr, values, quote=True):
    """``attr IN ('a', 'b')`` - for fetching linked features by identifier."""
    if quote:
        vals = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
    else:
        vals = ", ".join(str(int(v)) for v in values)
    return f"{attr} IN ({vals})"


def batches(values, size):
    values = sorted(values)
    return [values[i:i + size] for i in range(0, len(values), size)]


# ---------------------------------------------------------------------------------------------- joined copies
# Attributes copied from a linked feature into the holder's joined copy (the first two present are used).
JOIN_ATTRS = ("description", "name1_text", "designatedname1_text", "oslandusetiera", "oslandusetierb",
              "address", "classification_desc", "roadclassification", "designation", "restriction",
              "routehierarchy", "postcode", "usrn", "uprn", "buildinguse", "access_purpose", "changetype")


def join_attrs(sample):
    """The (up to two) descriptive attributes worth copying from a feature type into another's joined copy."""
    present = []
    for name in JOIN_ATTRS:
        if any(p.get(name) not in (None, "", []) for p in sample):
            present.append(name)
        if len(present) == 2:
            break
    return present


def count_field(link):
    """Column counting incoming links in the target's joined copy, e.g. 'n_building_primary_site' (Buildings
    whose primary Site this is) or 'n_siteaccesslocation'; spatial ones end '_sp'."""
    base = short(link["holder"])
    same = [lk for lk in LINKS if lk["holder"] == link["holder"] and lk["target"] == link["target"]
            and lk["kind"] == link["kind"]]
    if len(same) > 1:
        base += "_" + link["id"].replace(short(link["holder"]) + "_", "")
    if link["kind"] == "spatial":
        base += "_sp"
    return "n_" + re.sub(r"[^a-z0-9_]", "_", base.lower())[:40]


def field_prefix(link, side="target"):
    """Column prefix in a joined copy, e.g. 'site_' for Building -> Site. Distinguishes two links to the
    same feature type (Building -> primary Site vs all Sites) by the link id."""
    other = link[side]
    same = [lk for lk in LINKS if lk["holder"] == link["holder"] and lk[side] == other and lk["kind"] == link["kind"]]
    base = short(other)
    if len(same) > 1:
        base = link["id"].replace(short(link["holder"]) + "_", "")
    return re.sub(r"[^a-z0-9_]", "_", base.lower())[:24] + "_"


# ---------------------------------------------------------------------------------------------- the quick picks
# Questions this plugin can answer from the APIs it uses (OS NGD API - Features and the OS Places API). Joins
# that need OS Select+Build - wards and parishes, council tax and Land Registry, planned and historic addresses,
# retail areas, catchments - are shown in the tree as 'Only with OS Select+Build' instead.
_SHOW = {r["key"]: r for r in SHOWCASE_RECIPES}
_OLD = {r["name"][:2]: r for r in RECIPES}

_EVERYTHING = {
    "subject": A, "title": "Everything about each property (one row per address)", "colour_by": "building_use",
    "only_in_area": True,
    "columns": [c for c in _ANSWERS["1."]["columns"] if c[0] not in ("building_osid", "site_osid")] + [
        ("parent_uprn", "Parent address (block) UPRN", ["address_parent"], "attr", ["uprn"]),
        ("street", "Street", ["address_street"], "attr", _STREET),
        ("usrn", "USRN", ["address_street"], "attr", ["usrn"]),
        ("street_authority", "Street authority", ["address_street"], "attr",
         ["responsibleauthority_name", "administrativearea1_text"]),
        ("maintained", "Street maintenance", ["address_street", "maintenancearea_street"], "list",
         ["maintenanceresponsibility"]),
        ("highway_dedication", "Highway dedication", ["address_street", "highwaydedication_street"], "list", _DESC),
        ("street_designations", "Street designations", ["address_street", "specialdesignationarea_street"], "list",
         ["designation"]),
        ("postcode_area_m2", "Postcode area (m²)", ["address_pcarea"], "attr", _AREA),
        ("site_addresses", "Addresses belonging to the site", ["building_uprn", "building_primary_site",
                                                               "site_addresses"], "count", []),
        ("building_osid", "Building ID", ["building_uprn"], "attr", ["osid"]),
        ("site_osid", "Site ID", ["building_uprn", "building_primary_site"], "attr", ["osid"]),
    ]}
_TRANSPORT = {
    "subject": "trn-ntwk-roadlink", "title": "Bus, cycle and tram on each road (one row per road link)",
    "colour_by": "road_class",
    "columns": [
        ("road", "Road", [], "attr", _DESC),
        ("road_name", "Road name", [], "attr", ["name1_text"]),
        ("road_class", "Road classification", [], "attr", ["roadclassification"]),
        ("length_m", "Length (m)", [], "attr", _LENGTH),
        ("street", "Street", ["roadlink_street"], "list", _STREET),
        ("bus_lanes", "Bus lanes", ["buslane_roadlink"], "count", []),
        ("bus_lane_pct", "Bus lane (% of length)", [], "attr", ["presenceofbuslane_overallpercentage"]),
        ("cycle_lanes", "Cycle lanes", ["cyclelane_roadlink"], "count", []),
        ("cycle_lane_types", "Cycle lane types", ["cyclelane_roadlink"], "list", _DESC),
        ("cycle_lane_pct", "Cycle lane (% of length)", [], "attr", ["presenceofcyclelane_overallpercentage"]),
        ("tram", "Trams on the road", ["tramonroad_roadlink"], "count", []),
        ("street_lights", "Street lights", ["streetlight_roadlink"], "count", []),
        ("pavement_pct", "Pavement (% of length)", [], "attr", ["presenceofpavement_overallpercentage"]),
        ("dedication", "Highway dedication", ["highwaydedication_roadlink"], "list", _DESC),
        ("restrictions", "Restrictions", ["restriction_roadlink"], "list", ["restriction"]),
        ("hazards", "Routing hazards", ["routinghazard_roadlink"], "list", _DESC),
        ("structures", "Bridges, barriers and other structures", ["routingstructure_roadlink"], "list", _DESC),
        ("road_osid", "Road Link ID", [], "attr", ["osid"]),
    ]}
_NAMES = {
    "subject": "gnm-fts-crowdsourcednamepoint", "title": "Local names (one row per crowd-sourced name)",
    "colour_by": "named_kind",
    "columns": [
        ("local_name", "Local name", [], "attr", ["name1_text", "name", "crowdsourcedname"]),
        ("named_kind", "What it names", [], "attr", _DESC),
        ("address", "Address it names", ["crowdsourced_uprn"], "attr", ["address"]),
        ("street", "Street it names", ["crowdsourced_street"], "attr", _STREET),
        ("site", "Site it names", ["crowdsourced_site"], "attr", _DESC),
        ("site_name", "Site name", ["crowdsourced_site"], "attr", _SITE_NAME),
        ("road", "Road it names", ["crowdsourced_road"], "attr", ["name1_text", "roadclassificationnumber"]),
        ("water", "Water it names", ["crowdsourced_water"], "attr", _DESC),
        ("building_part", "Building part it names", ["crowdsourced_buildingpart"], "attr", _DESC),
        ("structure", "Structure it names", ["crowdsourced_structure"], "attr", _DESC),
        ("land", "Land it names", ["crowdsourced_land"], "attr", _DESC),
    ]}
_WALKING = {
    "subject": "trn-ntwk-pathlink", "title": "Paths (one row per path link)", "colour_by": "path_type",
    "columns": [
        ("path_type", "Path", [], "attr", _DESC),
        ("path_name", "Path name", ["pathlink_path"], "list", ["name1_text", "designatedname1_text"]),
        ("length_m", "Length (m)", [], "attr", _LENGTH),
        ("street", "Street (USRN)", ["pathlink_street"], "list", _STREET),
        ("connections_to_roads", "Connections to the road network at its ends",
         ["pathlink_nodes", "connectinglink_pathnode"], "count", []),
        ("path_osid", "Path Link ID", [], "attr", ["osid"]),
    ]}


def _pick(key, name, question, path, answers, types, links, answer, note="", filters=None):
    return {"key": key, "name": name, "question": question, "path": path, "answers": answers, "types": types,
            "links": links, "answer": answer, "note": note, "filters": filters or {}}


def _from(r, key, name, question=None):
    return dict(r, key=key, name=name, question=question or r["question"])


RECIPES = [
    _pick("everything", "1. Tell me everything about this property",
          "Tell me everything about this property.",
          "Address (UPRN) → Building → Building Part → Site; → Street (USRN) → highway records; → postcode",
          "The address and its type; its building in full (use, age, height, floors, roof, floor area) and how "
          "many addresses share it; its site and land use; its parent block; its street, who maintains it and "
          "its designations; its postcode.",
          [A, "bld-fts-building", "bld-fts-buildingpart", "lus-fts-site", "trn-ntwk-street",
           "trn-rami-maintenancearea", "trn-rami-highwaydedication", "trn-rami-specialdesignationarea",
           "asu-gbpcd-postcodeunitarea"],
          ["building_uprn", "building_parts", "building_primary_site", "building_sites", "buildingpart_site",
           "site_uprn", "site_addresses", "address_parent", "address_street", "maintenancearea_street",
           "highwaydedication_street", "specialdesignationarea_street", "address_pcarea"],
          _EVERYTHING,
          note="Council tax, business rates, Land Registry titles, wards and parishes need OS NGD GB Address from "
               "OS Select+Build - see 'Only with OS Select+Build' in the tree."),
    _from(_SHOW["street"], "street", "2. Which street is it on, and who looks after it?"),
    _from(_SHOW["access"], "access", "3. How do emergency services reach a site?"),
    _from(_SHOW["postcode"], "postcode", "4. What is each postcode like?"),
    _from(_OLD["2."], "site", "5. What is a site made of?"),
    _from(_SHOW["site_mix"], "site_mix", "6. Which sites are residential, commercial or mixed?"),
    _from(_SHOW["housing"], "housing", "7. What are the buildings like?"),
    _from(_SHOW["solar"], "solar", "8. Which roofs could take solar panels?"),
    _from(_SHOW["green"], "green", "9. How green is each site?"),
    _from(_SHOW["community"], "community", "10. Where are the schools, health, emergency and community sites?"),
    _from(_OLD["7."], "utility", "11. Which utility sites are here, and what's on them?"),
    _from(_OLD["6."], "roads", "12. What does each road serve?"),
    _pick("transport", "13. Which roads have bus, cycle or tram lanes?",
          "How is each road used by buses, bikes and trams - and what restricts it?",
          "Road Link ← Bus Lane, Cycle Lane, Tram on Road, Street Light, RAMI records",
          "Bus and cycle lanes (count and % of length), trams, street lights, pavement, highway dedication, "
          "restrictions, hazards and structures on every road link.",
          ["trn-ntwk-roadlink", "trn-ntwk-street", "trn-ntwk-buslane", "trn-ntwk-cyclelane", "trn-ntwk-tramonroad",
           "trn-fts-streetlight", "trn-rami-highwaydedication", "trn-rami-restriction", "trn-rami-routinghazard",
           "trn-rami-routingstructure"],
          ["roadlink_street", "buslane_roadlink", "cyclelane_roadlink", "tramonroad_roadlink",
           "streetlight_roadlink", "highwaydedication_roadlink", "restriction_roadlink", "routinghazard_roadlink",
           "routingstructure_roadlink"], _TRANSPORT,
          note="Traffic regulation orders and NaPTAN stops are Department for Transport data, not in OS's APIs."),
    _pick("walking", "14. Can you walk or cycle there?",
          "Where do the paths go, and where do they meet the roads?",
          "Path Link → Path Node ← Connecting Link; Path Link → Path, Street",
          "Every path link with its type, name, length and street, and how many connections to the road network "
          "it has at its ends.",
          ["trn-ntwk-pathlink", "trn-ntwk-pathnode", "trn-ntwk-path", "trn-ntwk-street", "trn-ntwk-connectinglink"],
          ["pathlink_nodes", "pathlink_path", "pathlink_street", "connectinglink_pathnode"], _WALKING),
    _pick("names", "15. What do local people call it?",
          "Which places, streets and buildings have local names?",
          "Crowd Sourced Name Point → Address, Street, Site, Road, Water, Building Part, Structure, Land",
          "Every crowd-sourced local name and the address, street, site, road or feature OS has matched it to.",
          ["gnm-fts-crowdsourcednamepoint", A, "trn-ntwk-street", "lus-fts-site", "trn-ntwk-road", "wtr-fts-water",
           "bld-fts-buildingpart", "str-fts-structure", "lnd-fts-land"],
          ["crowdsourced_uprn", "crowdsourced_street", "crowdsourced_site", "crowdsourced_road", "crowdsourced_water",
           "crowdsourced_buildingpart", "crowdsourced_structure", "crowdsourced_land"], _NAMES,
          note="Names come from the public and are matched by OS - treat them as aliases."),
]
SHOWCASE_RECIPES = []      # folded into RECIPES above
