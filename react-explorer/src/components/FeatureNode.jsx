import { Handle, Position } from "@xyflow/react";

/** A feature type box, sized to its name, with a stripe down the left in its theme's colour. The feature being
 *  looked at is drawn dark; other organisations' datasets get a dashed border. */
export default function FeatureNode({ data }) {
  const cls = ["feature-node", data.focus && "is-focus", data.external && "is-external"].filter(Boolean).join(" ");
  const ports = data.ports ?? { in: [{ id: "in" }], out: [{ id: "out" }] };
  return (
    <div
      className={cls}
      style={{ width: data.width, height: data.height, "--theme": data.themeColor }}
      title={data.about || data.title}
    >
      {ports.in.map((p) => (
        <Handle key={p.id} id={p.id} type="target" position={Position.Left} isConnectable={false}
                style={p.top !== undefined ? { top: p.top } : undefined} />
      ))}
      <div className="feature-node__title">{data.title}</div>
      <div className="feature-node__sub">{data.sub}</div>
      {ports.out.map((p) => (
        <Handle key={p.id} id={p.id} type="source" position={Position.Right} isConnectable={false}
                style={p.top !== undefined ? { top: p.top } : undefined} />
      ))}
    </div>
  );
}
