import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { loadData } from "./lib/data";
import "./styles.css";

const root = createRoot(document.getElementById("root"));

loadData()
  .then(() =>
    root.render(
      <StrictMode>
        <App />
      </StrictMode>
    )
  )
  .catch((err) => {
    // most often: the page was opened straight from disk, where browsers block reading the data files
    const fromDisk = window.location.protocol === "file:";
    root.render(
      <div className="load-error">
        <h1>The relationship data didn't load</h1>
        <p>{err.message}</p>
        {fromDisk && (
          <p>
            This page was opened straight from a folder, and browsers don't let it read <code>ngdhierarchy.json</code>{" "}
            that way. Open it through a local web server instead: in VS Code, right-click the HTML file and choose{" "}
            <strong>Open with Live Server</strong>.
          </p>
        )}
      </div>
    );
  });
