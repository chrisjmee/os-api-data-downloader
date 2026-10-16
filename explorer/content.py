"""Written content for the OS NGD Data Linkages Explorer: the linking keys, how the two delivery routes differ,
and the use cases. The relationships themselves come from OS's relationship model
(explorer/data/os_relationships.csv) - every use-case step below must be a row in it (checked at build)."""

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

# ------------------------------------------------------------------------------------------ linking keys
# key id: matched against the TARGET join key of each relationship
KEYS = [
    {"id": "osid", "name": "OSID", "full": "OS identifier", "who": "Ordnance Survey",
     "format": "36-character GUID",
     "what": "The primary identifier of every OS NGD feature: a 36-character GUID. It stays with the feature "
             "while the feature is updated and is retired if the feature is removed. Older OS MasterMap "
             "products used the TOID for the same job.",
     "use": "Most links inside OS NGD point at an OSID: a building's site, a road link's start and end nodes, "
            "the road link a restriction applies to.",
     "open": "Every OS NGD feature, through both the API and Select+Build."},
    {"id": "uprn", "name": "UPRN", "full": "Unique Property Reference Number",
     "who": "Local authorities create them; GeoPlace and Ordnance Survey maintain them", "format": "Number, up to 12 digits",
     "what": "Up to 12 digits, one for every addressable thing - houses, flats, shops, schools, but also "
             "things without a postal address, planned properties and ones since demolished. A UPRN never "
             "changes and is never reused.",
     "use": "The key that joins addresses to buildings, sites, council tax and business rates, Land Registry "
            "titles and most public-sector property records.",
     "open": "OS Open UPRN gives every UPRN and its location free. The OS Places API looks up the address "
             "for a UPRN; OS NGD GB Address (Select+Build) holds the full records."},
    {"id": "usrn", "name": "USRN", "full": "Unique Street Reference Number",
     "who": "Highway and street authorities, through the National Street Gazetteer (GeoPlace)", "format": "Number, up to 8 digits",
     "what": "Up to 8 digits, one for every street, including private roads, footpaths and alleys. Street "
             "works, maintenance and traffic orders are all recorded against it.",
     "use": "Joins an address to its street, and a street to who maintains it, its designations, street "
            "works reinstatement, traffic orders and the road links that carry it.",
     "open": "OS Open USRN gives every USRN and its extent free; OS NGD Street and RAMI carry the detail."},
    {"id": "postcode", "name": "Postcode", "full": "Royal Mail postcode", "who": "Royal Mail", "format": "Outward and inward code, e.g. SO16 0AS",
     "what": "A delivery grouping of around 15 addresses on average. Postcodes are created, split and "
             "retired, so they are a grouping to report by, not a property key.",
     "use": "Joins addresses to postcode units, and postcode units to the areas they fall in (council, ward, "
            "NHS area).",
     "open": "OS NGD GB Postcodes (API and Select+Build); ONS's postcode directories add statistical areas."},
    {"id": "udprn", "name": "UDPRN", "full": "Unique Delivery Point Reference Number", "who": "Royal Mail",
     "format": "8-digit number",
     "what": "An 8-digit number for each Royal Mail delivery point. One UPRN can have several UDPRNs, but not "
             "the other way round.",
     "use": "Joins an OS address to the Royal Mail Postcode Address File record.",
     "open": "In OS NGD GB Address (Select+Build)."},
    {"id": "gsscode", "name": "GSS code", "full": "Government Statistical Service code",
     "who": "Office for National Statistics", "format": "9 characters: a letter and 8 digits",
     "what": "A 9-character code for every statistical and administrative area - countries, councils, wards, "
             "parishes, health areas. A new code is issued when a boundary changes.",
     "use": "Joins features and addresses to the areas used for reporting, statistics and service delivery.",
     "open": "OS Boundaries in OS NGD; ONS's Open Geography Portal publishes the codes and lookups."},
    {"id": "uarn", "name": "UARN", "full": "Unique Address Reference Number", "who": "Valuation Office Agency",
     "format": "Number",
     "what": "The Valuation Office Agency's reference for each property it values for council tax or "
             "business rates.",
     "use": "Joins an OS address (UPRN) to its council tax band or rateable value record.",
     "open": "The cross-reference sits in OS NGD GB Address (Select+Build)."},
    {"id": "atcocode", "name": "ATCO code", "full": "NaPTAN stop code", "who": "Department for Transport",
     "format": "Up to 12 characters",
     "what": "The identifier of each public transport access point in NaPTAN - bus stops, stations, ferry "
             "terminals.",
     "use": "Joins OS ferry terminals to the national stop list.",
     "open": "NaPTAN is open data from the Department for Transport."},
    {"id": "waterbodyid", "name": "Water body ID", "full": "Water Framework Directive water body identifier",
     "who": "Environment agencies", "format": "Text, starting GB",
     "what": "The identifier of each river basin district or water body catchment used in water management.",
     "use": "Joins OS water network links and catchments to the river basin districts they drain to.",
     "open": "OS NGD Water (catchments are in Select+Build and Tiles)."},
    {"id": "grid", "name": "Grid square", "full": "British National Grid square reference",
     "who": "Ordnance Survey", "format": "Letters and digits, e.g. SU3914",
     "what": "The reference of a 1 km, 100 m or 25 m square of the National Grid.",
     "use": "A neutral way to summarise or join data by area, such as retail areas against radon risk.",
     "open": "Grids are part of OS's reference data."},
    {"id": "featureid", "name": "Feature ID", "full": "Retail area identifier", "who": "Ordnance Survey",
     "format": "", "what": "The identifier of an aggregated retail area.",
     "use": "Joins minor and major retail areas to the aggregated retail area they belong to.",
     "open": "OS NGD Functional Areas (Select+Build)."},
    {"id": "other", "name": "Other identifiers", "full": "Island, Northern Ireland and partner identifiers",
     "who": "GeoPlace and partners", "format": "",
     "what": "Street and property identifiers used in the Channel Islands, Isle of Man and Northern Ireland, "
             "and composite keys agreed with partners such as the Canal and River Trust.",
     "use": "Joins OS addresses and structures to those organisations' own records.",
     "open": "Varies by partner."},
]
KEYS.append(
    {"id": "location", "name": "Location", "full": "A join worked out from where features are",
     "who": "You - calculated when you run it, not supplied by OS", "format": "Geometry (British National Grid)",
     "what": "When no stored key joins two things, their positions can: an address point inside an Output Area, a "
             "building inside a flood zone, the nearest watercourse. These joins are only shown when 'Include joins "
             "worked out from location' is ticked.",
     "use": "Answers questions OS's keys don't reach - statistical areas, environmental designations, distance to "
            "things - and fills gaps where a stored key is missing.",
     "open": "Needs both datasets with their geometry, and a GIS or spatial database (QGIS, PostGIS, DuckDB "
             "spatial). Results depend on positional accuracy and boundary edges, and are only as current as the "
             "last time you ran them."})

# joins worked out from location: (source, target, method, SQL-style test, note)
SPATIAL_FEATURES = {
    "FloodZones": {"title": "Flood Map for Planning (Flood Zones)", "org": "Environment Agency", "theme": "Water",
                   "subtheme": "Flood risk", "pk": ""},
    "ConservationAreas": {"title": "Conservation Areas", "org": "Historic England and local authorities",
                          "theme": "Land Use", "subtheme": "Designations", "pk": ""},
}
SPATIAL = [
    ("BuiltAddress", "OutputAreaDec21BFE", "Address point inside the area",
     "ST_Within(BuiltAddress.geometry, OutputAreaDec21BFE.geometry)",
     "The usual way to put addresses into Output Areas (and on to LSOAs and MSOAs) for census-based statistics."),
    ("BuiltAddress", "Building", "Address point inside the building footprint",
     "ST_Within(BuiltAddress.geometry, Building.geometry)",
     "A fallback where a building doesn't list the UPRN; address points can sit just outside small buildings."),
    ("BuiltAddress", "Site", "Address point inside the site",
     "ST_Within(BuiltAddress.geometry, Site.geometry)",
     "Every address inside a site, not just the ones the site lists - useful for campuses and estates."),
    ("Building", "Site", "Building's centre inside the site",
     "ST_Within(ST_PointOnSurface(Building.geometry), Site.geometry)",
     "A fallback where a building has no site reference."),
    ("Building", "LowerTierLocalAuthority", "Building's centre inside the council area",
     "ST_Within(ST_PointOnSurface(Building.geometry), LowerTierLocalAuthority.geometry)",
     "Building parts carry the council code; whole buildings don't, so this gives it for a building."),
    ("Site", "Ward", "Site's centre inside the ward",
     "ST_Within(ST_PointOnSurface(Site.geometry), Ward.geometry)",
     "Large sites can cross ward boundaries - use the overlap area instead if that matters."),
    ("Building", "PostcodeUnitArea", "Building's centre inside the postcode area",
     "ST_Within(ST_PointOnSurface(Building.geometry), PostcodeUnitArea.geometry)",
     "For buildings with no address of their own (garages, outbuildings)."),
    ("Building", "FloodZones", "Building overlaps the flood zone",
     "ST_Intersects(Building.geometry, FloodZones.geometry)",
     "Which buildings - and through their UPRNs, which addresses - are in Flood Zone 2 or 3."),
    ("BuiltAddress", "ConservationAreas", "Address point inside the conservation area",
     "ST_Within(BuiltAddress.geometry, ConservationAreas.geometry)",
     "Which properties need extra consent for changes. Boundaries come from each local authority."),
    ("Building", "Water", "Nearest water feature, within 50 m",
     "ST_DWithin(Building.geometry, Water.geometry, 50)",
     "Distance to rivers, lakes and the sea - choose the distance to suit the question."),
]

KEY_OF = {"osid": "osid", "uprn": "uprn", "usrn": "usrn", "postcode": "postcode", "udprn": "udprn",
          "gsscode": "gsscode", "uarn": "uarn", "atcocode": "atcocode", "waterbodyid": "waterbodyid",
          "grid1km": "grid", "grid100m": "grid", "gridid_25m": "grid", "featureid": "featureid"}

# ------------------------------------------------------------------------------------------ API vs Select+Build
DELIVERY = {
    "rows": [
        ("What it is", "A web service: ask for features in an area, or matching a filter, and get them back "
                       "straight away.",
         "An ordering service on the OS Data Hub: choose feature types and an area, and receive files."),
        ("Format", "GeoJSON (OS NGD API – Features); vector tiles (OS NGD API – Tiles).", "GeoPackage or CSV."),
        ("How much", "Up to 100 features per request, page by page; best for an area, a list of IDs or a "
                     "live look-up.", "Great Britain, a drawn area or a pre-defined area; best for large "
                                     "areas and whole feature types."),
        ("Keeping up to date", "Always the current data - ask again to get the latest.",
         "A full supply, then daily or monthly change-only updates (CSV only; not for drawn areas)."),
        ("History", "Current features only.", "A snapshot of a past date (from late 2022 for most feature types)."),
        ("Linking lists", "Lists such as uprnreference arrive inside each feature as a nested list - one "
                          "feature, many UPRNs.", "Lists such as uprnreference or relatedentity come as their "
                                                 "own reference tables - one row per link - joined to the "
                                                 "feature on its OSID."),
        ("What's included", "Most OS NGD themes. Not GB Address, Functional Areas (retail areas) or "
                            "Boundaries as features.", "Every OS NGD theme, including GB Address, Islands "
                                                         "Address, Functional Areas and Boundaries."),
        ("Cost", "Transactions per request, within your OS Data Hub plan.",
         "Part of the Premium and Public Sector plans."),
    ],
    "linking": [
        "A link written as uprnreference.uprn means: the uprn field in the feature's UPRN reference list. In "
        "the API that list is nested inside the feature; in Select+Build it is a separate reference table "
        "with one row per UPRN.",
        "Addresses (GB Address) are only in Select+Build. With the API, use the OS Places API to look up "
        "addresses by UPRN, postcode or area.",
        "Use the API to explore an area or follow a few links live; use Select+Build to join whole feature "
        "types in a database and keep them up to date.",
        "Reference tables can store identifiers as text where the target holds a number (a UPRN as a "
        "string, for example) - convert the type before joining.",
    ],
    "sources": [
        ("OS NGD: data ordering and currency", "https://docs.os.uk/osngd/getting-started/os-ngd-fundamentals/os-ngd-data-ordering-and-currency"),
        ("OS NGD: frequently asked questions", "https://docs.os.uk/osngd/using-os-ngd-data/faqs"),
    ],
}

# ------------------------------------------------------------------------------------------ use cases
# step: (source feature, source join key, target feature) - must be a row in the relationship file
USE_CASES = [
    {"id": "everything", "title": "Tell me everything about this property",
     "who": "Councils, emergency services, housing, revenues, insurers, property and asset managers",
     "summary": "Start from one UPRN and pull together everything OS data and its partners hold about the "
                "property: its building and site, its street and who maintains it, its postcode and areas, its "
                "Royal Mail address, council tax or business rates, Land Registry title and any parent address.",
     "steps": [("Building", "uprnreference.uprn", "BuiltAddress"),
               ("Building", "buildingpartreference.buildingpartid", "BuildingPart"),
               ("Building", "sitereference.siteid", "Site"),
               ("BuiltAddress", "parentuprn", "BuiltAddress"),
               ("BuiltAddress", "udprn", "RoyalMailAddress"),
               ("BuiltAddress", "usrn", "Street"),
               ("MaintenanceArea", "usrn", "Street"),
               ("BuiltAddress", "relatedentity.crossreferenceid", "RoadLink"),
               ("BuiltAddress", "postcode", "PostcodeUnitArea"),
               ("BuiltAddress", "lowertierlocalauthoritygsscode", "LowerTierLocalAuthority"),
               ("BuiltAddress", "relatedentity.crossreferenceid", "Ward"),
               ("BuiltAddress", "relatedentity.crossreferenceid", "ParishOrCommunity"),
               ("BuiltAddress", "relatedentity.crossreferenceid", "CouncilTax"),
               ("BuiltAddress", "relatedentity.crossreferenceid", "NonDomesticRates"),
               ("TitleNumberandUPRNLookUpdataset", "uprn", "BuiltAddress")],
     "answers": ["What is the full address, its classification (house, flat, shop, school…) and its Royal Mail "
                 "postal address?",
                 "Which building is it in - use, age, height, floors, footprint, roof, construction - and how many "
                 "other addresses share it?",
                 "Which site does it belong to and what is the land used for?",
                 "Is it a flat in a block (parent UPRN), and which other flats share the parent?",
                 "Which street is it on, which road link gives access, and is the street maintained at public "
                 "expense?",
                 "Which postcode, council, ward and parish is it in?",
                 "Does it have a council tax or business rates record, and which Land Registry title covers it?"],
     "watch": "This combines OS NGD (API and Select+Build), GB Address (Select+Build only) and partner data with "
              "their own licences - the address, VOA and Land Registry joins need GB Address from Select+Build."},
    {"id": "property", "title": "What is at this address?",
     "who": "Councils, housing, emergency planning, insurers, property analysts",
     "summary": "Start from a UPRN and build a full picture of the property: the building it is in, the "
                "building's parts and the site it belongs to.",
     "steps": [("Building", "uprnreference.uprn", "BuiltAddress"),
               ("Building", "buildingpartreference.buildingpartid", "BuildingPart"),
               ("Building", "sitereference.siteid", "Site"),
               ("Site", "mainbuildingid", "Building")],
     "answers": ["Which building is this address in, and what is it - use, age, height, floors, footprint?",
                 "How many other addresses share the building (flats, offices)?",
                 "Which site is it on - a school, hospital, industrial estate - and what is the site used for?",
                 "Is this the main building on the site?"],
     "watch": "A building can have many UPRNs and a UPRN can sit in a building with many parts - count "
              "distinct UPRNs, not rows."},
    {"id": "areas", "title": "Which council, ward and parish is it in?",
     "who": "Anyone reporting by area: councils, central government, NHS, police, statisticians",
     "summary": "Every address carries the codes of the administrative areas it lies in, so counts and "
                "service areas need no spatial query.",
     "steps": [("BuiltAddress", "lowertierlocalauthoritygsscode", "LowerTierLocalAuthority"),
               ("BuiltAddress", "relatedentity.crossreferenceid", "Ward"),
               ("BuiltAddress", "relatedentity.crossreferenceid", "ParishOrCommunity"),
               ("LowerTierLocalAuthority", "boundaryparentreference_id", "UpperTierLocalAuthority")],
     "answers": ["How many addresses, homes or businesses are in each council, ward or parish?",
                 "Which ward and councillor covers a property?",
                 "Which upper-tier (county) authority is responsible for a property?"],
     "watch": "GSS codes change when boundaries change - join on the codes for the date you're reporting."},
    {"id": "ownership", "title": "Who owns it, and what tax applies?",
     "who": "Revenues and benefits, fraud, estates, HM Land Registry users, valuation",
     "summary": "UPRNs join addresses to Land Registry titles and to the Valuation Office Agency's council "
                "tax and business rates records.",
     "steps": [("TitleNumberandUPRNLookUpdataset", "uprn", "BuiltAddress"),
               ("NationalPolygonDataset", "uprn", "BuiltAddress"),
               ("BuiltAddress", "relatedentity.crossreferenceid", "CouncilTax"),
               ("BuiltAddress", "relatedentity.crossreferenceid", "NonDomesticRates")],
     "answers": ["Which registered title (or titles) covers this property?",
                 "What is its council tax band or business rates record?",
                 "Which properties have an address but no council tax or rates record - potential missing "
                 "revenue?",
                 "Which land parcels go with which addresses?"],
     "watch": "Land Registry and VOA data have their own licences; the links are only as current as the "
              "last supply of each."},
    {"id": "street", "title": "Which street is it on, and who looks after it?",
     "who": "Highway authorities, street works, utilities, waste and road maintenance teams",
     "summary": "The USRN joins an address to its street, and the street to the highway records (RAMI) and "
                "to the road links that carry it.",
     "steps": [("BuiltAddress", "usrn", "Street"),
               ("MaintenanceArea", "usrn", "Street"),
               ("ReinstatementLine", "usrn", "Street"),
               ("SpecialDesignationLine", "usrn", "Street"),
               ("Street", "roadlinkreference.roadlinkid", "RoadLink")],
     "answers": ["Which street is each address on, and how many addresses does each street serve?",
                 "Is the street maintained at public expense, and by which authority?",
                 "What reinstatement type applies if it is dug up?",
                 "Is it traffic sensitive or otherwise designated?",
                 "Which road links make up the street, for routing and network analysis?"],
     "watch": "A long street can have many road links, and a road link can carry more than one street."},
    {"id": "access", "title": "How do emergency services reach a site?",
     "who": "Fire, ambulance and police control rooms, resilience teams, logistics",
     "summary": "Site access locations mark the real entrances to a site and the road node each one joins, "
                "so routing can aim for the right gate.",
     "steps": [("SiteAccessLocation", "accessedsiteid", "Site"),
               ("SiteAccessLocation", "accessednetworknodeid", "RoadNode"),
               ("RoadLink", "startnode", "RoadNode"),
               ("Restriction", "networkreferenceid", "RoadLink"),
               ("RoutingHazard", "networkreferenceid", "RoadLink"),
               ("RoutingStructure", "networkreferenceid", "RoadLink")],
     "answers": ["Where are the entrances to a hospital, school or industrial site, and which are for "
                 "emergency or public use?",
                 "Which road node does each entrance join, for routing to the right gate?",
                 "Are there height, weight or width limits, barriers or hazards on the approach?"],
     "watch": "Older Site Access Location versions used roadnodeid and siteid; the current version uses "
              "accessednetworknodeid and accessedsiteid."},
    {"id": "postcode", "title": "What is each postcode like?",
     "who": "Health, marketing, statistics, service planning",
     "summary": "Addresses group into postcode units, and each postcode unit point carries the council, ward "
                "and NHS areas it falls in.",
     "steps": [("BuiltAddress", "postcode", "PostcodeUnitArea"),
               ("PostcodeUnitArea", "postcode", "PostcodeUnitPoint"),
               ("PostcodeUnitPoint", "relatedentity.crossreferenceid", "Ward"),
               ("PostcodeUnitPoint", "relatedentity.crossreferenceid", "NHSHealthAuthority"),
               ("PostcodeUnitPoint", "relatedentity.crossreferenceid", "UpperTierLocalAuthority")],
     "answers": ["How many addresses, homes and businesses are in each postcode?",
                 "Which ward, council and NHS area does each postcode belong to?",
                 "What is the shape and size of each postcode area?"],
     "watch": "Postcodes change - a postcode is a grouping to report by, not a stable property key."},
    {"id": "site", "title": "What is a site made of?",
     "who": "Estates, planning, environmental and green-space teams",
     "summary": "Every piece of land, building part, water, structure, rail and road surface records the site "
                "it lies in, giving a complete picture of each site.",
     "steps": [("Land", "sitereference.siteid", "Site"),
               ("BuildingPart", "sitereference.siteid", "Site"),
               ("Water", "sitereference.siteid", "Site"),
               ("RoadTrackOrPath", "sitereference.siteid", "Site"),
               ("Structure", "sitereference.siteid", "Site"),
               ("Site", "sitetoaddressreference.uprn", "BuiltAddress")],
     "answers": ["How much of a site is built on, grass, trees, paved or water?",
                 "Which buildings, structures and roads belong to a school, hospital or utility site?",
                 "Which addresses belong to each site?"],
     "watch": "Features record both the smallest and the largest site they lie in - choose which one you "
              "mean, or count both deliberately."},
    {"id": "pipeline", "title": "Which planned homes have been built?",
     "who": "Housing delivery, planning monitoring, council tax and electoral registration",
     "summary": "Parent and child UPRNs link a planned development to the addresses built on it, and blocks "
                "of flats to their flats.",
     "steps": [("BuiltAddress", "parentuprn", "PrebuildAddress"),
               ("PrebuildAddress", "parentuprn", "PrebuildAddress"),
               ("BuiltAddress", "parentuprn", "BuiltAddress"),
               ("HistoricAddress", "parentuprn", "HistoricAddress")],
     "answers": ["How far through building is each development - how many of its planned addresses now "
                 "exist?",
                 "Which flats belong to which block?",
                 "Which addresses have been demolished or replaced?"],
     "watch": "A parent shell (the block) and its flats are all UPRNs - leave the parent out when counting "
              "homes."},
    {"id": "transport", "title": "How is a place served by transport?",
     "who": "Transport planners, councils, accessibility and active-travel teams",
     "summary": "Ferry terminals, bus and cycle lanes, traffic orders and public transport stops all join to "
                "the OS road and path networks.",
     "steps": [("FerryTerminal", "ferryterminalcode", "Naptan"),
               ("FerryTerminal", "roadnodeid", "RoadNode"),
               ("NationalPublicTransportAccessNodes", "usrn", "RoadLink"),
               ("DigitalTrafficRegulationOrders", "usrn", "RoadLink"),
               ("BusLane", "linkid", "RoadLink"),
               ("CycleLane", "roadlinkid", "RoadLink")],
     "answers": ["Which roads have bus or cycle lanes, and how much of each?",
                 "Which stops and terminals connect to which part of the network?",
                 "Which traffic orders apply to a road?"],
     "watch": "NaPTAN and traffic orders join by USRN to the nearest road link - check where a street has "
              "several links."},
    {"id": "walking", "title": "Can you walk or cycle there?",
     "who": "Active travel, public health, accessibility and rights of way teams",
     "summary": "The path network joins to the road network through connecting links and nodes, and pavement "
                "links run alongside road links.",
     "steps": [("PathLink", "startnode", "PathNode"),
               ("Path", "pathlinkreference.pathlinkid", "PathLink"),
               ("ConnectingLink", "pathnodeid", "PathNode"),
               ("ConnectingNode", "roadlinkid", "RoadLink"),
               ("PavementLink", "roadlinkid", "RoadLink"),
               ("Street", "pathlinkreference.pathlinkid", "PathLink")],
     "answers": ["Is there a continuous walking route between two places, on and off road?",
                 "Which roads have a pavement?",
                 "Which streets are footpaths or alleys?"],
     "watch": "Paths and roads are separate networks - routes across both need the connecting links."},
    {"id": "retail", "title": "How healthy is a town centre?",
     "who": "Economic development, planning, retail and property analysts",
     "summary": "Retail areas list the addresses inside them and the sites and streets that divide them, and "
                "roll up into aggregated retail areas and built-up areas.",
     "steps": [("RetailAreaMajor", "relatedentity.crossreferenceid", "BuiltAddress"),
               ("RetailAreaMinor", "retailareaaggregatedid", "RetailAreaAggregated"),
               ("RetailAreaAggregated", "builtupareaid", "BuiltUpArea"),
               ("RetailAreaMajor", "dividingfeature_siteid", "Site"),
               ("RetailAreaMajor", "relatedentity.crossreferenceid", "Grid1km")],
     "answers": ["How many addresses are in each retail area, and of what type?",
                 "Which retail areas make up a town's aggregated retail area?",
                 "How do retail areas compare by 1 km square?"],
     "watch": "Retail area cross-references are text, while UPRNs in GB Address are numbers - convert before "
              "joining. Retail areas update twice a year."},
    {"id": "water", "title": "Which catchment does it drain to?",
     "who": "Flood risk, water companies, environmental regulators",
     "summary": "The water network carries its catchment, and catchments join to river basin districts used in "
                "water management.",
     "steps": [("WaterLink", "catchmentid", "WaterCatchment"),
               ("WaterBodyCatchment", "riverbasindistrictid", "RiverBasinDistrict"),
               ("WaterLinkSet", "waterlinkreference.waterlinkid", "WaterLink"),
               ("WaterLink", "startnode", "WaterNode"),
               ("BuiltAddress", "relatedentity.crossreferenceid", "Water")],
     "answers": ["Which catchment and river basin district is a watercourse in?",
                 "Which named rivers are made of which water links?",
                 "Which addresses relate to water features (moorings, boats, waterside property)?"],
     "watch": "Catchments are in Select+Build and Tiles, not the Features API."},
    {"id": "names", "title": "What do local people call it?",
     "who": "Emergency call handlers, search, gazetteers",
     "summary": "Crowd-sourced names are matched to the address, street or feature they describe, so local "
                "names can be found and resolved.",
     "steps": [("CrowdSourcedNamePoint", "matcheduprn", "BuiltAddress"),
               ("CrowdSourcedNamePoint", "matchedusrn", "Street"),
               ("CrowdSourcedNamePoint", "matchedosid", "Site"),
               ("CrowdSourcedNamePoint", "matchedosid", "Road")],
     "answers": ["Which property, street or site does a local name refer to?",
                 "Can a caller's description ('the old mill', 'the rec') be resolved to a location?"],
     "watch": "Crowd-sourced names are matched by OS but come from the public - treat them as aliases."},
]

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
