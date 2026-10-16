import { Icon } from "./Icon";

type Props = {
  /** Its cover, once OpenAI has painted one. */
  url: string | null;
  /** Sizes and rounds it; the same for the picture and the radio icon standing in for it. */
  className: string;
  iconSize?: number;
};

/** A station's cover, or the radio icon until it has one. */
export function StationCover({ url, className, iconSize = 30 }: Props) {
  if (url) return <img src={url} alt="" loading="lazy" className={className} />;
  return (
    <span aria-hidden="true" className={className}>
      <Icon name="radio" size={iconSize} />
    </span>
  );
}
