import { DELIVERY, FEATURES, KEYS, keyStyle, linksOf, STORAGE } from "../lib/data";

function KeyChip({ id }) {
  const k = keyStyle(id);
  return (
    <span className="chip" style={{ background: k.color }}>
      {k.label}
    </span>
  );
}

function LinkRow({ link, other, onSelect, onFocus }) {
  return (
    <li className="link-row">
      <button type="button" className="link-row__name" onClick={() => onFocus(other)}>
        {FEATURES.get(other)?.title}
      </button>
      <span className="link-row__keys">
        {link.keys.map((k) => (
          <KeyChip key={k} id={k} />
        ))}
      </span>
      <button type="button" className="link-row__more" onClick={() => onSelect(link.id)} title="About this link">
        ›
      </button>
    </li>
  );
}

function FeatureDetails({ id, withExternal, onSelect, onFocus }) {
  const f = FEATURES.get(id);
  const { out, in: inn, self } = linksOf(id, withExternal);
  return (
    <>
      <p className="eyebrow">{f.theme} · {f.group}</p>
      <h2>{f.title}</h2>
      <p className={`delivery delivery--${f.delivery}`}>{f.delivery === "external" ? f.org : DELIVERY[f.delivery]}</p>
      {f.about && <p>{f.about}</p>}
      {f.api && (
        <p className="muted small">
          API collection: <code>{f.api}</code>
        </p>
      )}
      {out.length > 0 && (
        <>
          <h3>Stores the IDs of ({out.length})</h3>
          <ul className="link-list">
            {out.map((l) => (
              <LinkRow key={l.id} link={l} other={l.target} onSelect={onSelect} onFocus={onFocus} />
            ))}
          </ul>
        </>
      )}
      {inn.length > 0 && (
        <>
          <h3>Its ID is stored by ({inn.length})</h3>
          <ul className="link-list">
            {inn.map((l) => (
              <LinkRow key={l.id} link={l} other={l.source} onSelect={onSelect} onFocus={onFocus} />
            ))}
          </ul>
        </>
      )}
      {self.length > 0 && (
        <>
          <h3>Links to other {f.title} records</h3>
          {self.map((l) => l.sentences.map((s) => <p key={s} className="small">{s}</p>))}
        </>
      )}
      {!out.length && !inn.length && <p className="muted">No links with the current settings.</p>}
    </>
  );
}

function LinkDetails({ link, onFocus }) {
  const s = FEATURES.get(link.source);
  const t = FEATURES.get(link.target);
  return (
    <>
      <p className="eyebrow">Link</p>
      <h2>
        <button type="button" className="text-link" onClick={() => onFocus(s.id)}>{s.title}</button>
        <span className="arrow"> → </span>
        <button type="button" className="text-link" onClick={() => onFocus(t.id)}>{t.title}</button>
      </h2>
      {link.meaning.length > 0 && <p className="meaning">{link.meaning.join(", ")}</p>}
      {link.sentences.map((x) => (
        <p key={x}>{x}</p>
      ))}
      <h3>How to join</h3>
      <table className="joins">
        <thead>
          <tr>
            <th>{s.title} attribute</th>
            <th>{t.title} attribute</th>
            <th>Key</th>
          </tr>
        </thead>
        <tbody>
          {link.joins.map((j) => (
            <tr key={j.field + j.targetField}>
              <td><code>{j.field}</code><br /><small className="muted">{STORAGE[j.storage]?.label}</small></td>
              <td><code>{j.targetField}</code></td>
              <td><KeyChip id={j.key} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">OS relationship type: {[...new Set(link.joins.map((j) => j.osType))].join(", ")}</p>
      {[...new Set(link.joins.map((j) => j.purpose).filter(Boolean))].map((p) => (
        <p key={p} className="small">{p}</p>
      ))}
      {link.keys.map((k) => KEYS.get(k)).filter(Boolean).map((k) => (
        <div key={k.id} className="key-note">
          <KeyChip id={k.id} /> <strong>{k.full}</strong>
          <p className="small">{k.what}</p>
        </div>
      ))}
    </>
  );
}

export default function Details({ focus, selected, withExternal, onSelect, onFocus, onClose }) {
  return (
    <aside className="details">
      {selected && (
        <button type="button" className="details__back" onClick={onClose}>
          ‹ Back to {FEATURES.get(focus)?.title ?? "feature"}
        </button>
      )}
      {selected ? (
        <LinkDetails link={selected} onFocus={onFocus} />
      ) : focus ? (
        <FeatureDetails id={focus} withExternal={withExternal} onSelect={onSelect} onFocus={onFocus} />
      ) : null}
    </aside>
  );
}
