import { useEffect, useState } from "react";
import { api, type Voices } from "../api";

let asked: Promise<Voices> | null = null;

/** GuildFM's voices: OpenAI's, and the ElevenLabs account's own. Asked for once per visit;
 * null until they arrive, or if they can't be had. */
export function useVoices(): Voices | null {
  const [voices, setVoices] = useState<Voices | null>(null);
  useEffect(() => {
    let wanted = true;
    asked ??= api<Voices>("GET", "/voices").catch((error) => {
      asked = null; // ask again next time
      throw error;
    });
    asked.then((found) => wanted && setVoices(found)).catch(() => {});
    return () => {
      wanted = false;
    };
  }, []);
  return voices;
}

/** An ElevenLabs voice, which understands tags such as [laughs]. */
export const isEleven = (voice: string) => voice.startsWith("elevenlabs:");

/** A voice's name to show: "Marin", or an ElevenLabs voice's own name. */
export function voiceName(voice: string, voices: Voices | null): string {
  if (!isEleven(voice)) return voice.charAt(0).toUpperCase() + voice.slice(1);
  return voices?.elevenlabs.find((found) => found.id === voice)?.name ?? "ElevenLabs voice";
}
