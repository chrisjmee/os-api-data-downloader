import { DELIVERY, FEATURES, KEYS, keyStyle, LINKS, linksOf, STORAGE } from "../lib/data";

/** A linking key shown the same way as in the key: a short line in its colour and its name. */
function KeyChip({ id }) {
  const k = keyStyle(id);
  return (
    <span className="keytag">
      <i style={{ background: k.color }} />
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

function CaseDetails({ uc, onSelect, onFocus }) {
  return (
    <>
      <p className="eyebrow">Use case</p>
      <h2>{uc.title}</h2>
      {uc.who && <p className="muted small">For: {uc.who}</p>}
      <p>{uc.summary}</p>
      {uc.answers.length > 0 && (
        <>
          <h3>Questions it answers</h3>
          <ul className="answers">
            {uc.answers.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </>
      )}
      <h3>Links it follows ({uc.links.length})</h3>
      <ol className="steps">
        {uc.links.map((id) => {
          const l = LINKS.get(id);
          return (
            <li key={id}>
              <button type="button" className="text-link" onClick={() => onSelect(id)}>
                {FEATURES.get(l.source).title} → {FEATURES.get(l.target).title}
              </button>{" "}
              {l.keys.map((k) => (
                <KeyChip key={k} id={k} />
              ))}
              {l.source === l.target && <span className="muted small"> (between records of the same type, not drawn)</span>}
            </li>
          );
        })}
      </ol>
      {uc.watch && (
        <p className="watch">
          <strong>Watch out: </strong>
          {uc.watch}
        </p>
      )}
    </>
  );
}

export default function Details({ focus, useCase, selected, withExternal, onSelect, onFocus, onBack }) {
  const backTo = selected ? FEATURES.get(focus)?.title ?? useCase?.title : focus && useCase ? useCase.title : null;
  return (
    <aside className="details">
      {backTo && (
        <button type="button" className="details__back" onClick={onBack}>
          ‹ Back to {backTo}
        </button>
      )}
      {selected ? (
        <LinkDetails link={selected} onFocus={onFocus} />
      ) : focus ? (
        <FeatureDetails id={focus} withExternal={withExternal} onSelect={onSelect} onFocus={onFocus} />
      ) : useCase ? (
        <CaseDetails uc={useCase} onSelect={onSelect} onFocus={onFocus} />
      ) : null}
    </aside>
  );
}
