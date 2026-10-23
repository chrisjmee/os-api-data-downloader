import { useState } from "react";
import { DATA, featuresByTheme } from "../lib/data";

function FeatureSelect({ label, value, onChange, withExternal }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose a feature type…</option>
        {featuresByTheme("", withExternal).map(({ theme, items }) => (
          <optgroup key={theme} label={theme}>
            {items.map((f) => (
              <option key={f.id} value={f.id}>
                {f.title}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

export default function Sidebar({ focus, onFocus, route, onRoute, withExternal, onExternal }) {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState({});
  const [from, setFrom] = useState(route?.from ?? "");
  const [to, setTo] = useState(route?.to ?? "");
  const groups = featuresByTheme(filter, withExternal);
  const searching = filter.trim().length > 0;

  return (
    <aside className="sidebar">
      <section>
        <h2>Feature types</h2>
        <input
          className="search"
          type="search"
          placeholder="Search, e.g. building, street, ward"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className="theme-list">
          {groups.map(({ theme, items }) => {
            const isOpen = searching || open[theme] || items.some((f) => f.id === focus);
            return (
              <div key={theme} className="theme">
                <button
                  type="button"
                  className="theme__head"
                  aria-expanded={isOpen}
                  onClick={() => setOpen((o) => ({ ...o, [theme]: !isOpen }))}
                >
                  <span>{theme}</span>
                  <span className="theme__count">{items.length}</span>
                </button>
                {isOpen && (
                  <ul>
                    {items.map((f) => (
                      <li key={f.id}>
                        <button
                          type="button"
                          className={`feature-item${f.id === focus ? " is-active" : ""}`}
                          onClick={() => onFocus(f.id)}
                        >
                          {f.title}
                          <small>{f.group}</small>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
          {!groups.length && <p className="muted">Nothing matches “{filter}”.</p>}
        </div>
      </section>

      <section>
        <h2>How are two connected?</h2>
        <FeatureSelect label="From" value={from} onChange={setFrom} withExternal={withExternal} />
        <FeatureSelect label="To" value={to} onChange={setTo} withExternal={withExternal} />
        <div className="row">
          <button type="button" className="primary" disabled={!from || !to || from === to} onClick={() => onRoute({ from, to })}>
            Show route
          </button>
          <button type="button" onClick={() => { setFrom(to); setTo(from); }} disabled={!from && !to} title="Swap">
            ⇄
          </button>
        </div>
      </section>

      <section>
        <label className="check">
          <input type="checkbox" checked={withExternal} onChange={(e) => onExternal(e.target.checked)} />
          Include other organisations' datasets
        </label>
        <p className="muted small">
          {DATA.features.length} feature types and {DATA.links.length} links from the OS relationship model. Data v
          {DATA.version}, built {DATA.built}.
        </p>
      </section>
    </aside>
  );
}
