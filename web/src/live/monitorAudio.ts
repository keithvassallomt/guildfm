/** What monitor mode is playing, as the server sends it. */
export type MonitorState = {
  transport: "PLAYING" | "PAUSED_PLAYBACK" | "STOPPED" | "TRANSITIONING";
  /** The song or clip on now. `id` changes each time something starts. */
  item: { id: number; kind: "song" | "clip"; path: string | null; seconds: number } | null;
  /** Seconds into the item when the server sent this. */
  elapsed: number;
  volume: number;
  /** Clips over the music, such as announcements, and how many seconds ago each started. */
  overlays: { id: number; path: string; volume: number; age: number }[];
};

// A different note for each song, so a change of song is easy to hear.
const NOTES = [523.25, 587.33, 659.25, 783.99, 880];
const BEEP_SECONDS = 0.12;
const BEEPS_LOUDNESS = 0.5; // beeps are harsher than speech, so they sit a little lower
const DUCKED = 0.2; // the beeps under an announcement or the DJ
const LATE = 3; // seconds: a clip over the music that started longer ago than this is skipped

/** Plays monitor mode in this browser: beeps for each song, and GuildFM's own clips (the DJ,
 * jingles and announcements) for real. Make one in a click handler: browsers only allow sound
 * after the person has done something. */
export class MonitorAudio {
  private context = new AudioContext();
  private beeps = this.context.createGain();
  private timer: number;
  private state: MonitorState | null = null;
  private itemId: number | null = null;
  private note = NOTES[0];
  private nextBeep = 0;
  private beat = 0;
  private clip: HTMLAudioElement | null = null;
  private overlays = new Set<HTMLAudioElement>();
  private heard = new Set<number>();

  constructor() {
    this.beeps.connect(this.context.destination);
    this.timer = window.setInterval(() => this.schedule(), 200);
  }

  apply(state: MonitorState) {
    this.state = state;
    const volume = state.volume / 100;
    const item = state.item;
    const playing = state.transport === "PLAYING" && item !== null;

    if ((item?.id ?? null) !== this.itemId) {
      this.itemId = item?.id ?? null;
      this.clip?.pause();
      this.clip = null;
      this.nextBeep = 0;
      this.beat = 0;
      if (item) this.note = NOTES[item.id % NOTES.length];
    }

    if (playing && item.kind === "clip" && item.path) {
      if (!this.clip) {
        const clip = new Audio(item.path);
        const from = state.elapsed;
        clip.addEventListener("loadedmetadata", () => {
          if (from > 0.5) clip.currentTime = from;
        });
        this.clip = clip;
      }
      this.clip.volume = volume;
      if (this.clip.paused) this.clip.play().catch(() => {});
    } else {
      this.clip?.pause();
    }

    for (const overlay of state.overlays) {
      if (this.heard.has(overlay.id)) continue;
      this.heard.add(overlay.id);
      if (overlay.age > LATE) continue;
      const audio = new Audio(overlay.path);
      audio.volume = overlay.volume / 100;
      const done = () => {
        this.overlays.delete(audio);
        this.duck();
      };
      audio.addEventListener("ended", done);
      audio.addEventListener("error", done);
      this.overlays.add(audio);
      audio.play().catch(done);
    }
    this.duck();
  }

  /** Stop all sound for good. */
  close() {
    window.clearInterval(this.timer);
    this.clip?.pause();
    this.overlays.forEach((audio) => audio.pause());
    this.overlays.clear();
    this.context.close().catch(() => {});
  }

  private beeping(): boolean {
    const state = this.state;
    return state?.transport === "PLAYING" && state.item?.kind === "song";
  }

  /** Lower the beeps while anything is said over them. */
  private duck() {
    const volume = (this.state?.volume ?? 0) / 100;
    const level = volume * BEEPS_LOUDNESS * (this.overlays.size > 0 ? DUCKED : 1);
    this.beeps.gain.setTargetAtTime(level, this.context.currentTime, 0.05);
  }

  /** Line up the next beep, a second after the last: one per second, a lower one on the beat. */
  private schedule() {
    if (!this.beeping()) return;
    const now = this.context.currentTime;
    if (this.nextBeep < now) this.nextBeep = now + 0.05;
    if (this.nextBeep > now + 0.4) return;
    const tone = this.context.createOscillator();
    const envelope = this.context.createGain();
    tone.frequency.value = this.beat % 4 === 0 ? this.note / 2 : this.note;
    envelope.gain.setValueAtTime(0.0001, this.nextBeep);
    envelope.gain.exponentialRampToValueAtTime(1, this.nextBeep + 0.01);
    envelope.gain.exponentialRampToValueAtTime(0.0001, this.nextBeep + BEEP_SECONDS);
    tone.connect(envelope).connect(this.beeps);
    tone.start(this.nextBeep);
    tone.stop(this.nextBeep + BEEP_SECONDS);
    this.nextBeep += 1;
    this.beat += 1;
  }
}
