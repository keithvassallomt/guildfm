import type { QueueEntry } from "../api";
import { credit } from "../live/status";
import { Avatar } from "./Avatar";

/** Who a queued song is from, with the requester's photo: "Requested by Priya". */
export function Credit({ entry, size = 16 }: { entry: QueueEntry; size?: number }) {
  const person = entry.requested_by;
  return (
    <>
      {person && <Avatar name={person.display_name} url={person.avatar_url} size={size} inline />}
      {credit(entry)}
    </>
  );
}
