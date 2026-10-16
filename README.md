# OS API Data Downloader (QGIS plugin)

*Created by CJM*

Get OS data for **just your area**, clipped to it, from three OS Data Hub APIs:

| Tab | API | What you get |
|---|---|---|
| **Find an NGD Feature Type** | OS Labs search tool + OS NGD API – Features | Search what an OS NGD feature is *described as* (e.g. "bridge") to find its feature type, then download it |
| **NGD Data Linkages** | OS NGD API – Features + OS Places API | Pick feature types *and the links between them* in a tree (Building → Site, Road Link → Road Node, Street by USRN, addresses by UPRN…) and download them already joined: link tables, joined copies and QGIS relations |
| **OS NGD** | OS NGD API – Features (OGC API – Features) | Any OS National Geographic Database feature type (buildings, land, sites, road links, water…) |
| **OS MasterMap** | OS Features API (OGC WFS) | OS MasterMap Topography Layer (`Topography_TopographicArea`, `_TopographicLine`, `_CartographicText`…), OS MasterMap Highways and the other WFS feature types, including annual snapshots |
| **OS Addressing** | OS Places API | Every address in the area, chosen by classification (Residential, Commercial, Education…), as one layer or a layer per classification |
| **OS Data Packages** | OS Downloads API | OS OpenData products (as the 100 km tiles covering your area, or GB) and your premium / PSGA data packages |

QGIS 3.28 or later (also written for QGIS 4 / Qt6). No extra Python packages.

## Install

*Plugins → Manage and Install Plugins → Install from ZIP* → `os_api_data_downloader-<version>.zip`. The toolbar
button opens the dock (also under *Web → OS API Data Downloader*).

On the **Settings** tab, save your OS Data Hub API key. Its project needs *OS NGD API – Features*,
*OS Features API*, *OS Places API* and *OS Downloads API*. **Test** checks all three without using any transactions.
OpenData downloads work without a key.

## Search for an address or place

The search box at the top of the panel finds addresses and places in one list. Type or paste an
address, postcode, UPRN or place name and press Enter.

- **◼ Named areas**: OS NGD Geographic Names (Named Area), shown with their county/district to help tell
  similarly-named places apart, e.g. "Broughton, Lancashire". Choosing one zooms to it and makes its real
  boundary the area of interest, so every tab downloads for that boundary.
- **Addresses**: OS Places, Royal Mail and council addresses, each property shown once. Choosing one
  shows its UPRN, postcode and classification and zooms to it.

Place names are only looked up when what you typed has no numbers in it (a house number, postcode or
UPRN means an address), so an address search doesn't cost an extra transaction. *Add to map* keeps the
chosen address or boundary in a layer.

## Area of interest and clipping

The panel at the top is shared by every tab:

- **Map view**: exactly what's in the map window.
- **Window**: a rectangle you drag on the map (*Draw window*).
- **Polygon**: any shape (*Draw polygon*: click the corners, right-click to finish).
- **Selected polygons in** a layer, such as a site boundary or a ward.
- **Named area**: a place chosen from the search box at the top (its real boundary).

*Clear* removes a drawn shape. **Clip** is either *cut features at the edge of the area* or *keep whole
features that touch the area*.

## NGD Data Linkages tab

OS NGD feature types are connected - a Building holds the OSID of its primary Site, a Site Access Location
the Site and Road Node it joins, a Road Link its start and end Road Nodes and the USRN of its Street, a
Building its UPRNs. This tab downloads feature types **with those links already made**.

**The tree** follows the Find tab: themes → feature types → links. Tick a feature type to download it; under
it are its links, in plain English - under Building, *→ The Site it mainly belongs to*; under Site, *← Buildings
that mainly belong to this Site*. Ticking a link ticks both feature types it joins. Colours give the link's class (from the *OS NGD Relationship Knowledge
Specification v2*): blue = explicit identifier, green = network topology, brown = authoritative containment,
orange `⇢` = spatially derived. Selecting a row explains it underneath: the attribute that carries it, its
cardinality, class and caveats. Greyed-out entries (administrative units, retail areas, Select+Build-only
cross-reference tables) aren't served by the APIs this plugin uses. Double-click a feature type (or
**⧩ Filter…**) to download only some of it, e.g. only *School* Sites.

- **Quick pick → Show off OS NGD** - eight picks built to show what OS NGD holds, each with the
  residential / commercial / mixed-use address split (numbers and %) and a *Character* column for colouring
  (mainly residential, mainly commercial, mixed…):

  | Pick | One row per… | Highlights |
  |---|---|---|
  | Site address mix | site | addresses through its buildings, residential / commercial / mixed counts and %, homes and addresses per hectare, floor area per address, main address and main building |
  | Housing stock profile | building | detached / semi / terrace, age, floors, height, materials, floor area per home, address mix, postcodes and streets |
  | Street profile (USRN) | street | addresses and mix, buildings and their ages, road length, addresses per 100 m, road class, pavement, maintenance, highway dedication, special designations, restrictions |
  | Postcode profile | postcode | addresses and mix, densities, building ages and types, tallest building, floor area per address, sites and streets |
  | Solar and roof potential | building | roof area facing each of 8 directions, flat roof, usable roof, panels already fitted, High / Medium / Low potential, addresses that would benefit |
  | Green and sealed land | site | m² and % under grass, trees, gardens, paving, buildings, water and roads; % green, % sealed, green space per home, address mix |
  | Site access and network | entrance | who it's for, distance to the network, roads and paths joined, width, dedication, restrictions, barriers, addresses on the site |
  | Community facilities | education / health / emergency / community / utility site | facility group, buildings, floor area, address mix, entrances and the roads that serve it |

  Each answer counts its postcodes, sites, streets or buildings **in full**, even where they reach beyond
  your drawn area: those are downloaded first, then everything else is read over the area widened to cover
  them (up to 1 km², or 4 × your area). Parent shells (the record for a whole block of flats) aren't counted
  on top of the flats. Spatial links (worked out from location) are off by default: the quick picks use OS's own identifiers
  and cross-references, so a site's addresses come through its buildings. Tick **Show spatial links** first
  to add them.
- **Quick pick → Answer a question** starts from a question rather than a list of layers. Each one ticks the feature types and
  links that answer it and explains the path underneath:
  1. *Property and address intelligence* - "Tell me everything about this property" (Address → Building →
     Building Part → Site → land use)
  2. *Site understanding* - "What makes up this site?" (Site → buildings, addresses, roads, structures, land,
     water, entrances)
  3. *Emergency services access* - "How do I get into this site?" (Site → Site Access Location → Road Node →
     Road Link, plus restrictions)
  4. *Building context* - "What surrounds this building?" (Building → Site → address → postcode / street →
     roads)
  5. *Education analysis* - Sites narrowed to schools, colleges, universities and nurseries, with their
     buildings, addresses, entrances and road access
  6. *Transport impact assessment* - "What does this road serve?" (Road Link → Road Node → Site Access
     Location → Site → buildings)
  7. *Utility and infrastructure discovery* - Sites narrowed to utility sites, with their structures,
     buildings and addresses
  8. *Asset management* - buildings, main building and address counts per site
  9. *Land use exploration* - "What is this area used for?" (every topographic area → Site → land use Tier
     A / B)
  10. *How are two feature types connected?* - pick a start and an end (e.g. Address and Road Link); the
     shortest chain of links between them is ticked and each step explained.

  Further down are whole networks for data engineers (road with routing information, path, street works by
  USRN, water, rail) and *Everything available*. Local authority and ward boundaries aren't served by the
  OS NGD API, so *Building context* uses the postcode instead.
- **Link everything ticked** ticks every link between the feature types you've ticked.
- **Show spatial links** adds links worked out from geometry (address inside Building Part, access point
  on the edge of a Site…). They're useful where no identifier link exists, but are derived, not
  authoritative, and are labelled so everywhere.

**Addresses** aren't in the OS NGD API - Features, so the *Address* feature type reads OS Places (needs
*OS Places API* on the key): every address in the area, plus any UPRN a ticked link points at. Ticking
*Address → Street (USRN)* adds the LPI record, which carries the USRN.

**Show me: Just the answer** (the default). For a Quick pick question you get **one layer that answers it** -
one row per address, site, entrance or road, with plain columns ("Building use", "Addresses in the
building", "Site name", "Land use", "In your area"…), coloured by its main category, with its attribute table
opened for you. Click any feature with Identify (or hover with Map Tips on) to read its answer. The layers it
was built from sit, switched off, in *Supporting layers*. The answer layers are:

| Quick pick | Answer layer - one row per… | What's in it |
|---|---|---|
| 1 Property | address | the address and its type; its building in full (use, detached/semi/terrace, age, year built, floors, height, eaves height, construction and roof material, roof shape, solar panels, green roof, basement, condition, footprint, south-facing and flat roof area, **estimated floor area**); addresses in the building and their mix; **floor area and footprint per address**; building parts; site, site name, land use, site area, buildings on the site; local authority (ONS code) |
| 2 Site understanding | site | site, name, land use (Tier A/B), operator, status, NLUD class, **area (m² / ha)**; buildings, their total floor area, tallest, most floors, ages, solar panels, roof areas, **plot ratio**; addresses and their mix, OS address counts, **homes and addresses per hectare**, whether addresses agree with the land use; entrances and their types; structures; land cover; **site composition - m² and % under buildings, grass, trees, made surface, gardens, water, roads/paths** |
| 3 Emergency access | site entrance | access for / by, network, metres to the road; the site, its area, how many entrances and how many for emergencies; buildings, tallest, most floors, building entrances; road names, classes, **narrowest road width**, pavement, restrictions and barriers |
| 4 Building context | building | the building in full (as in 1); OS and linked address counts and mix, **floor area per address**; site and land use; postcodes, streets, town, street authority, local authority, postcode area |
| 5 Education | education site | as Site understanding, plus building entrances, roads and road names giving access, least pavement on them, **% green space** and **open ground not under buildings** (for e.g. playing fields or battery siting) |
| 6 Transport impact | road link | road, name, number, class, route hierarchy, **length, width, narrowest**, one-way, pavement, street lighting, bus and cycle lanes, climb; street and street authority; site entrances, sites served (count, which, names), buildings and **addresses on those sites** |
| 7 Utility | utility site | site core details, structures (count, what, area), structure points, buildings and their floor area, height, solar, roofs, main address, ground composition |
| 8 Asset management | site | site core details, buildings, floor area, tallest, ages, solar, main building, **footprint and % built over**, addresses and mix, OS counts, **density per hectare**, **floor area per address**, address types |
| 9 Land use | site | site core details, whether addresses agree with the land use and the address-based land use, counts of building parts, land, water and structures, land cover, **full composition %**, **% green space**, **% sealed surface**, local authority |

Floor area is estimated as footprint × number of floors. Composition uses OS's own record of what lies in
each site (smallest and largest site), measured by OS's `geometry_area_m2`. Building height, age, floors,
materials, roof and solar details come from the newer OS NGD Building attributes; where your data doesn't
carry one, its column is simply empty.

Wherever addresses are counted (quick picks 1, 2, 4, 5 and 8) the answer also breaks them down by type -
e.g. *"34 Residential (72%) / 12 Commercial (26%) / 1 Mixed use (2%)"* - with *% residential*,
*% commercial* and *% mixed use* as numbers for sorting or colouring, and the status line gives the same
breakdown for every address in your area. The types are OS Places' AddressBase classes (Residential,
Commercial, Dual use - shown as Mixed use -, Land, Military, Object of interest…).

The answer layer is made only in this view. Here the link tables stay in the GeoPackage rather than being
loaded into QGIS, which keeps big downloads quick.

**Show me: Everything** (for data engineers) gives every layer, joined copies and the link tables:

**What you get** - one GeoPackage, added to the map as a group:

| In the GeoPackage | What it is |
|---|---|
| a layer per feature type | `ngd_in_area` = 1 for features in your area, 0 for linked features fetched from outside it (kept whole) |
| `link_<link id>` tables | `from_key` → `to_key`, `via_field` (the attribute it came from, e.g. `startnode` or `endnode`), `target_found`, `from_in_area`, `to_in_area` |
| `ngd_link_register` | every ticked link in plain English (both ways round, and "each Building links to one Site…"), its type, cardinality, join key, the attribute actually used, how it was found, counts, checked date and source |
| `<layer>_joined` copies (optional - in the same file, or all together in a file of their own, `…_joined.gpkg`) | the layer plus, per link, `<prefix>key`, `<prefix>n` (how many), `<prefix>keys` (1:N, comma-separated) and up to two descriptive attributes of the linked feature (e.g. `primary_site_description`); incoming links add counts such as `n_building_primary_site` |

**QGIS relations** - named in plain English, which is what a feature's form shows - are added to the project
for every link (holder → link table → target, and directly
holder → target for single-valued links such as `primarysiteid` or `accessedsiteid`), so *Identify* on a
Site lists its Buildings, entrances and addresses in the feature form.

**Speed.** Requests go several at a time (every page of every feature type at once, once the estimate has
counted them), kept under the OS Data Hub limit of 600 a minute; writing and joining are done by GDAL and
SQLite rather than feature by feature. In testing that took a 500-transaction download from about 5½
minutes to just over 1.

**Linked features outside the area** (the Road Node at the far end of a Road Link, the rest of a school
Site, the Street a Road Link belongs to) are fetched by their ID - looked for within 500 m of the area, then
5 km, never across all of GB (which the API can take minutes to answer); anything further is reported - when *Fetch linked features outside the
area* is ticked - about one transaction per 40 features, one per address - and capped by *Stop after*. Links
to anything not fetched are kept with `target_found` = 0.

**Speed.** Pressing *Download* without an estimate does a quick count - one request per feature type,
whose first page the download then reuses - instead of the fuller *Estimate cost* count. Big feature types are
read in growing waves of pages, ten requests at a time (kept under OS's 600 a minute), and layers are opened in
the background so QGIS doesn't freeze when they're added. With a lot ticked over a big area the OS rate limit
is the floor: roughly a minute per 550 transactions.

**Keeping the cost down.** A linked ID is never asked for twice. Addresses are read in bulk (100 a
transaction) over the area plus 100 m, including OS Places' LPI records, so buildings at the edge and
non-postal UPRNs such as parent shells link without a transaction each; anything left is looked up one by
one, up to 150. A batch of IDs the server fails on is split and retried. The status line shows where the
transactions went.

**When OS's data doesn't carry a link.** If a Building's cross-references (its addresses, parts or sites), an
entrance's building or site, or a junction's name aren't in the downloaded data, the link is worked out from
location instead - an address inside the building, a part inside it, the building inside a site - so the
answers are still filled in. The status line and the link register say which links were worked out this way.

**Field names are checked, not assumed.** The specification warns that exact attribute names must be
validated against the delivered schema, so each link lists its expected attribute(s), the download looks
for them in the real features (then for any attribute naming the target, e.g. `...siteid`), and the
register records which was used - `schema`, `guess` (check it) or `not found`. A link that isn't in the
data is reported, never invented.

## NGD Data Linkages Explorer (web page)

An interactive, read-only guide to how OS National Geographic Database features join to each other and to
partner data - no QGIS, no API key, nothing to download:
**https://chrisjmee.github.io/os-api-data-downloader/ngd-links/**

- **Use cases** - 13 everyday questions (what is at this address, which ward is it in, who owns it, who
  maintains the street, how do emergency services reach a site…), the joins each one needs, the keys used and
  where to get each dataset.
- **Feature types** - every feature in OS's relationship model, what it joins to and the exact fields
  (`Building.uprnreference.uprn = BuiltAddress.uprn`).
- **Linking keys** - OSID, UPRN, USRN, postcode, GSS code, UDPRN, UARN and the rest: what each is, who issues
  it and every join that uses it.
- **Find a route** - the shortest chain of joins between any two features, with the key used at each step.
- **API or Select+Build?** - how the two delivery routes differ, and what that means for joining data.

The relationships come from OS's UK Geospatial Entity Relationships model (`explorer/data/os_relationships.csv`);
the written content is in `explorer/content.py`. `explorer/build_explorer.py` builds the page, and GitHub
rebuilds and republishes it whenever either changes. The built page, `docs/ngd-links/index.html`, is one
self-contained file that can also be emailed or opened offline.

## Find an NGD Feature Type tab

OS NGD has around 100 feature types with technical names (`str-fts-structure`, `trn-ntwk-pathlink`...) that
don't say much about what they actually contain. This tab is a way in: type what the thing is commonly
*described as* - e.g. `bridge`, `school`, `pylon` - and press **Search**.

Searching is a local lookup against a small **index** of every OS NGD feature type's description-style
attribute and its allowed values - not a live API call - so it's instant and needs no API key. The index
is either:

- **bundled with the plugin** - so a fresh install has something to search from the first run, or
- **your own**, built from your live API key with the **Rebuild index** button (a one-off check of every OS
  NGD feature type's queryables, so it takes a minute or two) - this always takes priority over the bundled
  one, and is the way to pick up feature types OS NGD has added or changed since the index was last built.
  There's no need to wait for a plugin update for that: press **Rebuild index** any time.

The tab's status line under the search box says which one you're currently searching, and when your own
was last built.

- Every matched feature type lists **each of its matched description values as its own tick box** - e.g.
  searching `bridge` under a structures feature type shows "Pipe Bridge" and "Weighbridge" separately.
  **Only the value(s) you tick are downloaded**, not the whole feature type - tick just "Weir" under a
  buildings feature type and only weirs come back, not every building part. Tick the feature type's own row
  to tick every value under it in one go.
- Results are grouped as **Polygons, then Lines, then Points**, and only the **most recent version** of
  each feature type is used - both come from the index, built fresh each time you rebuild it.
- The attribute to filter on is already known from the index, so estimating or downloading needs no extra
  lookup - if none could be found for a feature type when the index was built, the result tells you it
  downloaded the whole feature type instead of just your tick.
- Tick any values you want (across as many feature types as you like) and use **Estimate cost** /
  **Download selected for my area** exactly as on the OS NGD tab - each ticked feature type becomes a layer
  in the same kind of GeoPackage, named after your search term and the values you ticked (e.g.
  `os_ngd_bridge_footbridge_pylon_20261012_155851.gpkg`) so it's obvious what's in it without opening it.
  In the Layers panel, each layer is named after the value(s) you ticked (e.g. "Footbridge") rather than
  the technical feature type id, and shows its feature count.
- **Clear selection** unticks everything.

If nothing useful turns up, try a more general word, rebuild the index in case it's out of date, or browse
the full list on the **OS NGD** tab instead.

Instead of typing a term, the **"...or pick one:"** drop-down lists every description value in the index -
type into it to filter the list, or just scroll it, then choose one to search for it directly.

### Building the index outside QGIS

`scripts/build_ngd_index.py` does the same job as **Rebuild index**, but from a terminal: a plain Python 3
script (no QGIS, no extra packages) that checks every OS NGD feature type's queryables with your API key
and writes the CSV. Useful for generating the copy bundled with the plugin itself, or for running from CI:

```
python3 scripts/build_ngd_index.py --api-key YOUR_KEY
```

The key can also come from the `OS_API_KEY` or `OS_PLACES_API_KEY` environment variable. By default it
writes to `data/ngd_feature_types.csv` - the plugin's own bundled copy.

## OS NGD and OS MasterMap tabs

1. Press **Load list**, then tick the feature types you want. They're listed in alphabetical order,
   with version numbers in numerical order. Type in the box to filter the list. **Clear selection** unticks
   everything.
2. Optionally, **⧩ Filter** a feature type on its attributes, in the same way as the OS Data Hub's
   filter options. See *Filtering features* below.
3. **Estimate cost** counts the features in your area. OS MasterMap uses the WFS `resultType=hits`,
   which costs one transaction per type. OS NGD API returns no counts, so the plugin makes a few
   one-feature test requests instead.
4. **Download for my area** fetches only the features in the area, 100 per transaction, into a new
   GeoPackage in your output folder (one layer per feature type), clips them, and adds them to the map
   in a group named after the source, area and time. The GeoPackage's own file name is built from the
   feature types in it too (e.g. `os_ngd_Building_Land_20261012_155851.gpkg`), and in the Layers panel
   each layer is named after its feature type (e.g. "Building") rather than the technical id, with its
   feature count shown next to it.

The area is sent to the API as a filter, so the API returns only features inside it:

- **OS NGD:** a CQL `INTERSECTS` filter.
- **OS MasterMap:** an OGC `BBOX` filter for a window or map view, and an `Intersects` filter for a
  polygon. If the service refuses a polygon filter, the plugin uses the polygon's bounding box instead.

Either way, results are clipped exactly to your shape afterwards. Large shapes are simplified outwards
for the filter so the request stays a sensible length; nothing inside your shape is ever missed.

### Filtering features

Highlight a feature type in the list (or double-click it) and press **⧩ Filter**. Build rules in the
same way as the OS Data Hub's *Advanced Filter Options*:

- **+ Add rule** adds an *attribute · operator · value* rule, for example *Description · is · Building*.
  The operators are: is, is not, is one of, contains, starts with, ends with, greater/less than, at
  least/most, between, is empty, and is not empty.
- **+ Add group** adds a set of rules that is worked out together. Each group, and the filter as a whole,
  can **match all** (and) or **match any** (or). For example: *(Building and Height > 15) or Shed*.
- **Values found in your area.** When the filter window opens, the plugin reads a sample of that feature
  type's features in your area: up to 500 features, at most 5 transactions. Each value drop-down then
  lists the values actually found there, such as every height or building type in the area, sorted
  numerically or alphabetically. The window says whether that was every feature in the area or the
  first 500. You can still type other values. The sample is remembered until the area changes, so
  reopening the window costs nothing. For *is one of*, each value picked from the list is added to the
  list of values.
- **Where the attributes come from.** For OS NGD, the attributes and their allowed values come from the
  API's queryables list, and the allowed values appear in a drop-down. For OS MasterMap, the attributes
  come from the WFS `DescribeFeatureType`.
- **Writing CQL yourself (OS NGD).** The query that will be sent is shown. To write your own CQL instead,
  tick *Write the query myself*.

The filter is applied on OS's server together with the area: `INTERSECTS(…) AND (filter)` for OS NGD,
and `<ogc:And>` for OS MasterMap. Only matching features are downloaded, so a narrow filter costs fewer
transactions, and the estimate counts matching features only.

A filtered feature type is shown in bold with *⧩ filtered*, and the rules are listed in words under the
list. **Remove filter** clears the filter.

You're asked before any download over the threshold set on Settings (default 1,000 transactions), and
**Stop after** caps a download. A capped download keeps what it has and says so.

On the OS MasterMap tab, **Data** chooses the latest data or an annual snapshot (`/wfs/archive/{year}`).
OS plans to retire the OS Features API in favour of OS NGD API (end of life expected in 2030).

## OS Addressing tab

1. Tick the classifications you want, from the AddressBase classification scheme:
   - **R** Residential
   - **C** Commercial, with sub-classes such as CE Education, CM Medical, CR Retail and CO Office
   - **X** Dual use
   - **L** Land
   - **M** Military
   - **Z** Objects of interest
   - **P** Parent shells
   - **U** Unclassified

   The list holds the full scheme, all 563 codes, at four levels:
   - **Primary**, e.g. *R Residential*
   - **Secondary**, e.g. *RD Dwelling*
   - **Tertiary**, e.g. *RD04 Terraced*
   - **Quaternary**, e.g. *CE01HE Higher Education* or *ZW99CH Church*

   Expand a class to pick only part of it. A partly ticked class shows a filled box. Type in the find
   box above the list (e.g. *terraced*, *school* or *CE03*) to show only the matching classifications,
   with their parents. The quick buttons tick *All*, *Residential*, *Commercial*, *Residential +
   commercial* or *None*.
2. Choose the addresses: Royal Mail postal (DPA), council (LPI, which also includes land, objects and other
   non-postal places), or both. With both, *One point per UPRN* keeps one point per property, using the
   Royal Mail address where there is one.
3. Choose the layers: one per main classification, one per sub-class (RD Dwelling, CE Education…), one
   per full classification code (RD04 Terraced, ZW99CH Church…), or all in one layer. With one layer per main
   classification, each layer has that class's own colour (Residential orange, Commercial blue…). With one
   per sub-class or per code, every layer gets a clearly different colour, so they are easy to tell apart
   on the map and in the Layers panel.

The classifications are filtered on the server, so asking for fewer costs fewer transactions. A very long
choice of detailed codes is sent to the server as up to 30 broader codes, then narrowed to exactly what you
ticked. The classification names come from Ordnance Survey's AddressBase classification scheme. OS Places
returns at most 1 km² per request, so the area is split into 1 km squares. Each square costs at least
one transaction, plus one per extra 100 addresses in it. Results are clipped to your exact area and saved
to a GeoPackage with the UPRN, address, postcode, organisation, classification code and description, DPA
or LPI, status, parent UPRN, USRN, UDPRN, TOID, local custodian and coordinates. The GeoPackage's file name
is built from the classifications ticked too (e.g. `os_places_Residential_20261012_155851.gpkg`), and each
layer already shows its feature count in the Layers panel.

## OS Data Packages tab

- **OS OpenData product**: press *Load list*, choose a product and format, then pick *Tiles covering my
  area* (only the 100 km squares your area touches) or *Great Britain*.
- **My data packages**: your premium / PSGA orders; choose the version.

Press *List files*, then download. With **Clip the downloaded data to my area** ticked, every layer in
the downloaded files is cut to your area and the smaller copies are added to the map. This covers
GeoPackage, Shapefile, GeoJSON, File Geodatabase (including inside ZIP files) and GeoTIFF rasters. The
full download is kept as well.

Clipping is built for big downloads:
- ZIPs are unpacked to a temporary folder first.
- The cutting is done inside GDAL (C++, the same engine as `ogr2ogr -spat -clipsrc`), so a GeoPackage's
  spatial index skips everything far from your area.
- Tiles are merged into one GeoPackage with one layer per theme, and rasters into one clipped GeoTIFF.

In tests, a 100 km tile with 800,000 features, supplied as a zipped GeoPackage, clipped to a 30 km area
in about 2.5 seconds (it used to take 3 minutes).

## Tests

`tests/qgis_smoke_apidownloader.py` drives the plugin in a headless QGIS against fake OS NGD, OS Features
(WFS) and OS Downloads servers. The fakes apply the area filters spatially, so the clipping results are
checked feature by feature.
