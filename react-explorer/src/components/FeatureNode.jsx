import { Handle, Position } from "@xyflow/react";

/** A feature type box. The focus feature is drawn dark; other organisations' datasets get a dashed border. */
export default function FeatureNode({ data }) {
  const cls = ["feature-node", data.focus && "is-focus", data.external && "is-external", data.dim && "is-dim"]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls} style={{ width: data.width }} title={data.about || data.title}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="feature-node__title">{data.title}</div>
      <div className="feature-node__sub">{data.sub}</div>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}
