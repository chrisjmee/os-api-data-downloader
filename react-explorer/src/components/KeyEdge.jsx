import { BaseEdge, getBezierPath } from "@xyflow/react";
import { keyStyle, STORAGE } from "../lib/data";

/** A link between two feature types, drawn as a smooth curve coloured by its linking key: solid when the
 *  ID is stored on the feature, dashed for a reference table, dotted for the Related Entity table.
 *  Clicking the line opens the link's details. */
export default function KeyEdge(props) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd, markerStart } = props;
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const link = data.link;
  return (
    <BaseEdge
      id={id}
      path={path}
      markerEnd={markerEnd}
      markerStart={markerStart}
      interactionWidth={16}
      style={{
        stroke: keyStyle(link.keys[0]).color,
        strokeWidth: data.selected ? 4 : 2.2,
        strokeDasharray: STORAGE[link.storage]?.dash,
        opacity: data.dim ? 0.15 : 1,
        cursor: "pointer",
      }}
    />
  );
}
