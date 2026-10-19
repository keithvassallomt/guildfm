import { Icon } from "./Icon";

type Props = {
  /** Its cover, once OpenAI has painted one. */
  url: string | null;
  /** Sizes and rounds it; the same for the picture and the icon standing in for it. */
  className: string;
  iconSize?: number;
};

/** A line-up's cover, or the line-up icon until it has one. */
export function LineupCover({ url, className, iconSize = 30 }: Props) {
  if (url) return <img src={url} alt="" loading="lazy" className={className} />;
  return (
    <span aria-hidden="true" className={className}>
      <Icon name="lineups" size={iconSize} />
    </span>
  );
}
