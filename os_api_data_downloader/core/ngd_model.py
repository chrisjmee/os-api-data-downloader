"""OS's UK Geospatial Entity Relationships model: every join OS records between OS NGD features and partner
data, and which of them this plugin can make through the APIs (OS NGD API - Features and OS Places API) -
the rest need OS Select+Build (or the partner's own data). Pure Python, no QGIS: the web explorer shares it."""
import csv
import os
import re

from . import ngd_links as NL

MODEL_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "os_relationships.csv")

# ------------------------------------------------------------------------------------------ data clean-up
# fixes for spelling slips in the relationship file, so each feature appears once
FEATURE_ALIASES = {"Roadlink": "RoadLink", "RodeTrackOrPath": "RoadTrackOrPath"}
KEY_ALIASES = {"ursn": "usrn"}
OWNER_ALIASES = {"Geoplace": "GeoPlace"}
FEATURE_TITLES = {
    "BGS/UKHSARadondata:IndicativeAtlasofRadon(GB)": "Indicative Atlas of Radon (GB)",
    "OutputAreaDec21BFE": "Output Area (Dec 2021, BFE)",
    "NHSHealthAuthority": "NHS Health Authority",
    "NHSRegionalHealthAuthority": "NHS Regional Health Authority",
    "Naptan": "NaPTAN",
    "NationalPublicTransportAccessNodes": "National Public Transport Access Nodes (NaPTAN)",
    "DigitalTrafficRegulationOrders": "Digital Traffic Regulation Orders",
    "TitleNumberandUPRNLookUpdataset": "Title Number and UPRN Look Up",
    "NationalPolygonDataset": "National Polygon Dataset",
    "GreaterLondonAuthorityAssemblyConstituency": "GLA Assembly Constituency",
    "Grid1km": "1 km Grid", "Grid100m": "100 m Grid",
    "RoyalMailAddress": "Royal Mail Address",
    "IsleofManStreetIdentifier": "Isle of Man Street Identifier",
    "ChannelIslandsStreetIdentifier": "Channel Islands Street Identifier",
    "ChannelIslandsUniqueIdentifier": "Channel Islands Unique Identifier",
    "NorthernIrelandStreetIdentifier": "Northern Ireland Street Identifier",
}

# relationship types grouped into families for colour
FAMILIES = {
    "within": ("Lies within", "One feature lies inside, or is part of, another (a building in a site, an address in a ward)."),
    "network": ("Network connection", "How a network is joined together: links, nodes, junctions, and records that apply to them."),
    "same": ("Same thing", "Two records describe the same real-world thing (a site's matched address, a VOA record for an address)."),
    "access": ("Access", "How a feature is reached: an entrance onto a road, an address onto its street."),
    "hierarchy": ("Parent and child", "A family of records: flats within a block, a planned address and the one built."),
    "spatial": ("Worked out from location", "Not supplied by OS: calculated from where the features are, for "
                                            "questions no stored key answers. Off unless you ask for it."),
}
TYPE_FAMILY = {
    "Spatially Within": "within", "Spatially Contained By": "within", "Intersects With": "within",
    "Aggregated To": "within", "Network Connection": "network", "Same As": "same", "Exact Fit": "same",
    "Best Fit": "same", "Accessed From": "access", "Nearest": "access", "Child Of": "hierarchy",
}


# ------------------------------------------------------------------------------------------ what each feature is
# one or two plain sentences, shown in the pop-up and at the top of each feature's page
FEATURE_INFO = {
    # Address
    "BuiltAddress": "Every current address that physically exists - homes, businesses, schools, flats - with its "
                    "UPRN, position, classification and links to its street, postcode and areas.",
    "PrebuildAddress": "Addresses for properties that are planned or under construction, before they are built.",
    "HistoricAddress": "Addresses that no longer exist - demolished, merged or otherwise retired - kept with their "
                       "UPRN for history.",
    "NonAddressableObject": "Things with a UPRN but no postal address: bus shelters, telephone boxes, car parks, "
                            "electricity substations, monuments.",
    "RoyalMailAddress": "Royal Mail's postal address (from the Postcode Address File) for each delivery point, "
                        "keyed by UDPRN.",
    "StreetAddress": "The street-level address record: street name, locality and town for each USRN.",
    "CouncilTax": "The Valuation Office Agency's council tax record for each home, keyed by UARN.",
    "NonDomesticRates": "The Valuation Office Agency's business rates (rateable value) record for each non-domestic "
                        "property, keyed by UARN.",
    "ChannelIslandsUniqueIdentifier": "The property identifier used by the Channel Islands' own address gazetteers.",
    # Administrative and statistical units
    "Country": "England, Scotland and Wales.",
    "Region": "The English regions (formerly government office regions).",
    "RegionalAuthority": "Combined and regional authorities, such as the Greater London Authority.",
    "UpperTierLocalAuthority": "County councils and unitary authorities - the upper tier of local government.",
    "LowerTierLocalAuthority": "District, borough, city and unitary councils - the lower tier of local government.",
    "LocalAuthorityDistricts": "ONS's local authority district boundaries and codes, used for official statistics.",
    "ElectoralDivision": "The areas that elect county councillors.",
    "Ward": "The areas that elect district, borough and unitary councillors.",
    "ParishOrCommunity": "Civil parishes in England and communities in Wales - the most local tier of government.",
    "PollingDistrict": "The areas each polling station serves at elections.",
    "DevolvedParliamentConstituency": "Constituencies for the Scottish Parliament and the Senedd.",
    "DevolvedParliamentElectoralRegion": "The regions that elect additional members to the Scottish Parliament and "
                                         "the Senedd.",
    "GreaterLondonAuthorityAssemblyConstituency": "The constituencies that elect London Assembly members.",
    "NHSHealthAuthority": "NHS health areas (such as Integrated Care Boards) that a postcode falls in.",
    "NHSRegionalHealthAuthority": "NHS regions that a postcode falls in.",
    "OutputAreaDec21BFE": "ONS's 2021 Census Output Areas - the smallest areas census statistics are published for "
                          "(around 125 households). Full-resolution boundaries.",
    "NationalPostcodeDirectory": "ONS's directory linking every postcode to the statistical and administrative areas "
                                 "it falls in.",
    "NationalPostcodeLookup": "ONS's best-fit lookup from postcodes to statistical areas.",
    "PostcodeUnitArea": "The area covered by each postcode, drawn from the addresses in it.",
    "PostcodeUnitPoint": "A single point for each postcode, with the codes of the areas it falls in.",
    "RetailAreaMinor": "Small clusters of shops and retail addresses.",
    "RetailAreaMajor": "Larger retail areas - town centres, high streets and shopping centres.",
    "RetailAreaAggregated": "Retail areas grouped into a single town or city retail centre.",
    # Building
    "Building": "A whole building: the building parts that make up one structure, with its use, age, height, "
                "floors, roof and the UPRNs of the addresses inside it.",
    "BuildingPart": "Each separately constructed part of a building, as drawn on the map, with its height and land "
                    "use.",
    "BuildingAccessLocation": "The entrances to a building - where people get in.",
    # Names
    "NamedPoint": "Named places shown as points: towns, villages, hills, landmarks.",
    "NamedArea": "Named places shown as areas: woods, estates, bays.",
    "NamedRoadJunction": "Named road junctions, such as motorway junctions and roundabouts.",
    "CrowdSourcedNamePoint": "Local and informal names suggested by the public and matched by OS to the feature, "
                             "address or street they describe.",
    "BuiltUpArea": "Built-up areas - the extent of towns and villages - as defined for statistics.",
    # Geology
    "BGS/UKHSARadondata:IndicativeAtlasofRadon(GB)": "The British Geological Survey and UK Health Security Agency "
                                                    "map of radon potential.",
    # Grids
    "Grid1km": "The 1 km squares of the British National Grid.",
    "Grid100m": "The 100 m squares of the British National Grid.",
    # Land
    "Land": "Every piece of land that isn't a building, road or water - grass, woodland, gardens, paved areas - with "
            "what it is and the site it lies in.",
    "LandPoint": "Small land features shown as points, such as individual trees or springs.",
    "Landform": "The shape of the land: cliffs, slopes, embankments, cuttings.",
    "LandformPoint": "Landform features shown as points, such as spot heights.",
    # Land parcels
    "NationalPolygonDataset": "HM Land Registry's index polygons showing the extent of registered titles.",
    "TitleNumberandUPRNLookUpdataset": "HM Land Registry's lookup from title numbers to the UPRNs of the properties "
                                       "they cover.",
    # Land use
    "Site": "A site with one purpose - a school, hospital, farm, industrial estate, park - with its land use and the "
            "buildings, land and addresses that belong to it.",
    "SiteAccessLocation": "The entrances to a site and the road or path node each one joins - where you actually "
                          "get in.",
    "SiteRoutingPoint": "An earlier way of giving a site's routing point; replaced by Site Access Location.",
    "ConservationAreas": "Areas of special architectural or historic interest designated by local authorities.",
    # Structures
    "Structure": "Built structures that aren't buildings: bridges, walls, towers, pylons, tanks.",
    "StructureLine": "Linear structures: walls, fences, hedges, retaining walls.",
    "StructurePoint": "Small structures shown as points: posts, masts, monuments.",
    "CompoundStructure": "Structures made of several parts, such as bridges, piers and dams, treated as one.",
    "FieldBoundary": "The hedges, walls and fences that divide fields.",
    "CanalBridges": "The Canal and River Trust's record of bridges over its waterways.",
    # Transport
    "RoadLink": "A stretch of road between two junctions or ends - the building block of the road network, with "
                "its name, class, width, speed and direction.",
    "RoadNode": "Where road links meet or end - junctions and dead ends.",
    "Road": "A named or numbered road made up of many road links, such as the A6.",
    "RoadJunction": "A junction made up of several road nodes, such as a large roundabout.",
    "RoadTrackOrPath": "The surface area of roads, tracks and paths, as drawn on the map.",
    "Street": "A street as recorded in the National Street Gazetteer, with its USRN, name and the authority "
              "responsible for it.",
    "PathLink": "A stretch of footpath, cycle path or track between two nodes - the building block of the path "
                "network.",
    "PathNode": "Where path links meet or end.",
    "Path": "A named path made up of path links, such as a long-distance trail.",
    "ConnectingLink": "The short links that join the path network to the road network.",
    "ConnectingNode": "Points on road links where the path network connects.",
    "PavementLink": "Pavements alongside road links.",
    "BusLane": "Bus lanes, with the road link they are on and when they apply.",
    "CycleLane": "Cycle lanes, with the road link they are on.",
    "TramOnRoad": "Where trams run on roads shared with traffic.",
    "StreetLight": "Street lighting along road links.",
    "FerryLink": "Ferry routes between terminals.",
    "FerryNode": "The ends of ferry routes.",
    "FerryTerminal": "Ferry terminals, linked to the road and path networks and to NaPTAN.",
    "Rail": "The surface area of railway land and track, as drawn on the map.",
    "RailwayLink": "A stretch of railway between two nodes - the building block of the rail network.",
    "RailwayNode": "Where railway links meet or end, including stations.",
    "RailwayLinkSet": "A named railway line made up of railway links.",
    "Restriction": "Legal and physical restrictions on roads: one way, no turn, height, width and weight limits.",
    "RoutingHazard": "Hazards for routing such as fords and level crossings.",
    "RoutingStructure": "Structures that affect routing: bridges, tunnels, barriers, gates.",
    "HighwayDedication": "Whether a road is a public highway, and for whom (all vehicles, pedestrians, cyclists…).",
    "MaintenanceArea": "Who maintains a street, as an area - for example maintained at public expense.",
    "MaintenanceLine": "Who maintains a street, as a line.",
    "MaintenancePoint": "Who maintains a street, as a point.",
    "ReinstatementArea": "The reinstatement standard for street works (how a road must be reinstated after digging), "
                         "as an area.",
    "ReinstatementLine": "The reinstatement standard for street works, as a line.",
    "ReinstatementPoint": "The reinstatement standard for street works, as a point.",
    "SpecialDesignationArea": "Special designations on streets - traffic sensitive, protected, special engineering "
                              "difficulty - as an area.",
    "SpecialDesignationLine": "Special designations on streets, as a line.",
    "SpecialDesignationPoint": "Special designations on streets, as a point.",
    "Naptan": "The national list of public transport access points - bus stops, stations, ferry terminals.",
    "NationalPublicTransportAccessNodes": "NaPTAN stops, joined to the street they're on.",
    "DigitalTrafficRegulationOrders": "Traffic regulation orders (speed limits, parking, restrictions) published in "
                                      "digital form.",
    "ChannelIslandsStreetIdentifier": "The street identifier used in the Channel Islands' gazetteers.",
    "IsleofManStreetIdentifier": "The street identifier used in the Isle of Man's gazetteer.",
    "NorthernIrelandStreetIdentifier": "The street identifier used in Northern Ireland's gazetteer.",
    # Water
    "Water": "The surface area of water: rivers, lakes, reservoirs, the sea, with the site it lies in.",
    "WaterPoint": "Small water features shown as points, such as springs and wells.",
    "WaterLink": "A stretch of watercourse between two nodes - the building block of the water network.",
    "WaterNode": "Where watercourses meet, start or end.",
    "WaterLinkSet": "A named watercourse made up of water links, such as a river.",
    "WaterCatchment": "The land area that drains to a stretch of watercourse.",
    "WaterBodyCatchment": "Catchments of the water bodies used in water management.",
    "RiverBasinDistrictCatchment": "Catchments grouped into river basin districts.",
    "RiverBasinDistrict": "The river basin districts used to manage water across Great Britain.",
    "InterTidalLine": "The lines of mean high and low water.",
    "FloodZones": "The Environment Agency's flood zones (2 and 3) for planning.",
}


# ------------------------------------------------------------------------------------------ loading
OS = "Ordnance Survey"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def title_of(name):
    if name in FEATURE_TITLES:
        return FEATURE_TITLES[name]
    t = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return re.sub(r"\bOr\b", "or", re.sub(r"\bAnd\b", "and", re.sub(r"\bOf\b", "of", t)))


def _version_major(v):
    m = re.match(r"\s*v?(\d+)", str(v))
    return int(m.group(1)) if m else None


def _version_num(v):
    m = re.match(r"\s*v?(\d+(?:\.\d+)?)\s*$", str(v))
    return float(m.group(1)) if m else None


def load(path=MODEL_CSV):
    """(features, edges): features {name: {title, org, theme, subtheme, pk, versions, latest}}; edges, one per
    distinct join, {s, t, sf, tf, type, family, join, owners, freq, sv, tv, purpose, old}."""
    with open(path, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    feats, edges, seen = {}, [], {}

    def feature(r, side):
        name = r[f"{side}Feature"].strip()
        name = FEATURE_ALIASES.get(name, name)
        f = feats.setdefault(name, {"id": name, "title": title_of(name), "org": r[f"{side}Organisation"].strip(),
                                    "theme": r[f"{side}Theme"].strip(), "subtheme": r[f"{side}SubTheme"].strip(),
                                    "pk": "", "versions": set()})
        pk = KEY_ALIASES.get(r[f"{side}PrimaryKey"].strip(), r[f"{side}PrimaryKey"].strip())
        if pk and pk != "tbc" and not f["pk"]:
            f["pk"] = pk
        if r[f"{side}Version"].strip():
            f["versions"].add(r[f"{side}Version"].strip())
        return name

    for r in rows:
        s, t = feature(r, "Source"), feature(r, "Target")
        sf = r["sourcejoinkey"].strip()
        tf = KEY_ALIASES.get(r["targetjoinkey"].strip(), r["targetjoinkey"].strip())
        rtype = r["RelationshipType"].strip()
        owner = OWNER_ALIASES.get(r["RelationshipOwner"].strip(), r["RelationshipOwner"].strip())
        k = (s, sf, t, tf, rtype)
        if k in seen:
            if owner and owner not in seen[k]["owners"]:
                seen[k]["owners"].append(owner)
            continue
        jt = r["JoinType"].strip()
        purpose = r["PurposeOfRelationship"].strip()
        e = {"s": s, "t": t, "sf": sf, "tf": tf, "type": rtype, "family": TYPE_FAMILY.get(rtype, "within"),
             "join": jt[:1].upper() + jt[1:], "owners": [owner] if owner else [],
             "freq": r["RelationshipUpdateFrequency"].strip(), "sv": r["SourceVersion"].strip(),
             "tv": r["TargetVersion"].strip(), "purpose": "" if purpose.lower() == "tbc" else purpose}
        seen[k] = e
        edges.append(e)
    for f in feats.values():
        nums = [v for v in f["versions"] if _version_num(v) is not None]
        f["latest"] = max(nums, key=_version_num) if nums else ""
        f["versions"] = sorted(f["versions"], key=lambda v: (_version_num(v) is None, _version_num(v) or 0, v))
        f["about"] = FEATURE_INFO.get(f["id"], "")
    for e in edges:
        latest, mine = _version_major(feats[e["s"]]["latest"]), _version_major(e["sv"])
        e["old"] = bool(latest is not None and mine is not None and mine < latest)
    return feats, edges


# ------------------------------------------------------------------------------------------ what this plugin can make
_BASES = {norm(b.rsplit("-", 1)[-1]): b for b, info in NL.TYPES.items()
          if info["available"] and not b.startswith("!") and b != NL.PLACES_ADDRESS}


def base_for(feature):
    """The plugin's feature type for a model feature (Built Address -> the OS Places address), or None when the
    APIs this plugin uses don't serve it."""
    if feature == "BuiltAddress":
        return NL.PLACES_ADDRESS
    return _BASES.get(norm(feature))


def plugin_link(edge):
    """The plugin link that makes this join, or None."""
    hb, tb = base_for(edge["s"]), base_for(edge["t"])
    if not hb or not tb:
        return None
    parts = [p.lower() for p in edge["sf"].split(".")]
    for lk in NL.LINKS:
        if lk["kind"] != "id":
            continue
        fields = [f.lower() for f in lk["fields"]]
        rev = [f.lower() for f in lk["rev"]]
        subs = [f.lower() for f in lk["sub"]]
        if lk["holder"] == hb and lk["target"] == tb and (parts[0] in fields or parts[-1] in subs):
            return lk["id"]
        if lk["holder"] == tb and lk["target"] == hb and (parts[0] in rev or (parts[0] == lk["key"] in fields)):
            return lk["id"]
    return None


def availability(edge, feats):
    """('api', link id) when this plugin can make the join; ('sb', reason) when it needs OS Select+Build;
    ('partner', reason) when it needs another organisation's data."""
    lid = plugin_link(edge)
    if lid:
        return "api", lid
    partners = [feats[f]["org"] for f in (edge["s"], edge["t"]) if feats[f]["org"] != OS]
    if partners:
        return "partner", f"Needs {partners[0]} data - not available through OS's APIs."
    missing = [feats[f]["title"] for f in (edge["s"], edge["t"]) if not base_for(f)]
    if missing:
        return "sb", (f"{' and '.join(dict.fromkeys(missing))} "
                      f"{'is' if len(set(missing)) == 1 else 'are'} only in OS Select+Build, not the OS NGD API - Features.")
    if edge["s"] == "BuiltAddress":
        return "sb", (f"Needs OS NGD GB Address from OS Select+Build - the OS Places API doesn't include "
                      f"{edge['sf']}.")
    return "sb", f"{edge['sf']} isn't in the data the OS NGD API - Features returns - it comes with OS Select+Build."


_CACHE = {}


def model():
    """(features, edges) with each edge's availability - read once."""
    if "m" not in _CACHE:
        feats, edges = load()
        for e in edges:
            e["avail"], e["why"] = availability(e, feats)
            e["link"] = e["why"] if e["avail"] == "api" else None
        _CACHE["m"] = (feats, edges)
    return _CACHE["m"]


def edges_for(base):
    """Model joins that touch this plugin feature type and that the plugin can't make (Select+Build / partner)."""
    feats, edges = model()
    return [e for e in edges if e["avail"] != "api" and not e["old"] and base in (base_for(e["s"]), base_for(e["t"]))]


def unreachable_features():
    """Model features the APIs don't serve at all (only in Select+Build, or partner data), with their joins."""
    feats, edges = model()
    out = {}
    for name, f in feats.items():
        if base_for(name):
            continue
        es = [e for e in edges if not e["old"] and name in (e["s"], e["t"])]
        if es:
            out[name] = es
    return out
