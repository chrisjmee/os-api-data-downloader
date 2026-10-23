# OS NGD Links (React)

A simple explorer of how OS NGD feature types join, built in React with React Flow. It uses the same data
as the OS NGD Data Linkages Explorer page in this repository: OS's relationship model
(`os_api_data_downloader/data/os_relationships.csv`), current schema versions only.

- **Pick a feature type** on the left. It sits in the middle; what it stores the IDs of is on the right,
  and what stores its ID is on the left.
- **Each line is coloured by its linking key** (OSID, UPRN, USRN, GSS code, postcode, others grey). A solid
  line means the ID is stored on the feature, dashed means it is listed in a reference table, dotted means the
  separate Related Entity table (Select+Build). The arrow points to the feature whose ID is stored.
- **Click a badge or line** for the attributes to join on, in plain English.
- **How are two connected?** shows every shortest chain of links between two feature types.
- The address bar follows what you look at (`#Street`, `#route=Building,Ward`), so views can be bookmarked
  and shared.

## Run it in VS Code

You need [Node.js](https://nodejs.org) 18 or later (and Python 3 only to refresh the data).

1. In VS Code, **File > Open Folder** and choose `react-explorer`.
2. Open a terminal (**Terminal > New Terminal**) and run, once:

   ```
   npm install
   ```

3. Start it:

   ```
   npm run dev
   ```

   Your browser opens at http://localhost:5173. Edits to files in `src/` show up as soon as you save.

The same commands are under **Terminal > Run Task**, and **Run and Debug** has Edge and Chrome debugging
set up (start `npm run dev` first).

## Refresh the data

```
npm run data
```

runs `explorer/export_react_data.py`, which rewrites `src/data/ngd-links.json` from the relationship model.
GitHub does this automatically before publishing.

## Share it

```
npm run build
```

writes a finished site to `dist/`. It works from any folder: open it with Live Server, copy it to a shared
drive or host it anywhere. GitHub publishes it at
https://chrisjmee.github.io/os-api-data-downloader/ngd-links-app/ whenever the data or app changes.

## Where things are

| File | What it does |
|---|---|
| `src/App.jsx` | The page, the two views (one feature, a route) and the legend |
| `src/components/Sidebar.jsx` | Feature list and search, route pickers, other-organisations switch |
| `src/components/Details.jsx` | Right-hand panel: a feature's links, or one link's join attributes |
| `src/components/FeatureNode.jsx` | The feature type boxes |
| `src/components/KeyEdge.jsx` | The lines and their key badges |
| `src/lib/data.js` | Loads the data; key colours; shortest-route search |
| `src/lib/layout.js` | Positions the boxes (dagre) |
| `src/styles.css` | All styling, light and dark |
| `src/data/ngd-links.json` | The data (generated, don't edit by hand) |
