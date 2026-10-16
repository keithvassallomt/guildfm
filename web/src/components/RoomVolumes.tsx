import type { Room } from "../api";
import styles from "./RoomVolumes.module.css";
import { VolumeSlider } from "./VolumeSlider";

type Props = { rooms: Room[]; onVolume: (uid: string, volume: number) => Promise<void> };

/** A volume slider for each room, saying which are on the TV or playing on their own. */
export function RoomVolumes({ rooms, onVolume }: Props) {
  return (
    <ul className={styles.rooms}>
      {rooms.map((room) => (
        <li key={room.uid}>
          <VolumeSlider
            label={
              <>
                <span className={styles.name}>{room.name}</span>{" "}
                <span className={styles.model}>{room.model.replace(/^Sonos /, "")}</span>
                {room.on_tv && <span className={styles.tag}>TV</span>}
                {!room.on_tv && !room.in_group && <span className={styles.tag}>Separate</span>}
              </>
            }
            value={room.volume}
            onCommit={(volume) => onVolume(room.uid, volume)}
          />
        </li>
      ))}
    </ul>
  );
}
