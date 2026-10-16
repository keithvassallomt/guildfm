import { useState } from "react";
import { Button } from "./Button";
import { PreviewButton } from "./PreviewButton";
import { FormError, TextField } from "./TextField";
import { isEleven } from "./useVoices";
import styles from "./VoicePreview.module.css";

const PHRASES = [
  "Lunch is ready in the kitchen. Come and get it while it's hot.",
  "Quick heads up: the fire alarm test is at ten. No need to leave the building.",
  "Friday drinks start in the Donut Shop at five. See you there.",
  "Welcome to everyone joining us this week. Say hello in the kitchen.",
];

/** Hear a voice say one of a few built-in phrases, or words typed in. Plays in the browser. */
export function VoicePreview({ voice }: { voice: string }) {
  const [phrase, setPhrase] = useState(PHRASES[0]);
  const [error, setError] = useState<string | null>(null);

  // A typed phrase isn't in the list, so the next one is the first.
  const another = () => setPhrase(PHRASES[(PHRASES.indexOf(phrase) + 1) % PHRASES.length]);

  return (
    <div className={styles.preview}>
      <TextField
        label="Hear it say"
        value={phrase}
        maxLength={600}
        hint={
          isEleven(voice)
            ? "Type your own words, with tags like [laughs] if you like, or try another of ours. Previews play here, not in the office."
            : "Type your own words, or try another of ours. Previews play here, not in the office."
        }
        onChange={(event) => setPhrase(event.target.value)}
      />
      <div className={styles.actions}>
        <Button variant="ghost" onClick={another}>
          Another phrase
        </Button>
        <PreviewButton text={phrase} extra={{ voice }} onError={setError} />
      </div>
      <FormError message={error} />
    </div>
  );
}
