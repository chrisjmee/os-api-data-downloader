import { BaseEdge, EdgeLabelRenderer, getBezierPath } from "@xyflow/react";
import { keyStyle, STORAGE } from "../lib/data";

/** A link between two feature types: coloured by its linking key, dashed when it comes from a reference table,
 *  with a badge naming the key. Clicking the line or the badge opens the link's details. */
export default function KeyEdge(props) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd, markerStart } = props;
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const link = data.link;
  const color = keyStyle(link.keys[0]).color;
  const width = data.selected ? 3.5 : link.storage === "both" ? 2.5 : 1.8;
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        markerStart={markerStart}
        interactionWidth={18}
        style={{ stroke: color, strokeWidth: width, strokeDasharray: STORAGE[link.storage]?.dash, opacity: data.dim ? 0.15 : 1 }}
      />
      <EdgeLabelRenderer>
        <button
          type="button"
          className={`key-badge nodrag nopan${data.selected ? " is-selected" : ""}`}
          style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly + (data.offset ?? 0)}px)`, background: color, opacity: data.dim ? 0.2 : 1 }}
          onClick={(e) => {
            e.stopPropagation();
            data.onSelect(link.id);
          }}
          title={link.sentences.join(" ")}
        >
          {link.keys.map((k) => keyStyle(k).label).join(" / ")}
          {link.storage === "table" || link.storage === "related" ? " ▤" : link.storage === "both" ? " +▤" : ""}
        </button>
      </EdgeLabelRenderer>
    </>
  );
}
