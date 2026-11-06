import { Icon } from "./Icon";
import s from "./Votes.module.css";

export type VoteValue = -1 | 0 | 1;

type Props = {
  title: string;
  mine: number; // -1, 0 or 1
  score: number;
  onVote: (value: VoteValue) => void;
};

/** Thumbs up, the score, thumbs down. Pressing the thumb you already gave takes it back. */
export function Votes({ title, mine, score, onVote }: Props) {
  const scoreClass = mine === 1 ? s.up : mine === -1 ? s.down : "";
  return (
    <div className={s.votes}>
      <button
        type="button"
        aria-label={`Thumbs up for ${title}`}
        aria-pressed={mine === 1}
        className={`${s.vote} ${mine === 1 ? s.up : ""}`}
        onClick={() => onVote(mine === 1 ? 0 : 1)}
      >
        <Icon name="thumbUp" size={20} filled={mine === 1} />
      </button>
      <span className={`${s.score} ${scoreClass}`} aria-label={`Score ${score}`}>
        {score > 0 ? `+${score}` : score}
      </span>
      <button
        type="button"
        aria-label={`Thumbs down for ${title}`}
        aria-pressed={mine === -1}
        className={`${s.vote} ${mine === -1 ? s.down : ""}`}
        onClick={() => onVote(mine === -1 ? 0 : -1)}
      >
        <Icon name="thumbDown" size={20} filled={mine === -1} />
      </button>
    </div>
  );
}
