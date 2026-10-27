import { Link, useLocation } from "react-router";
import styles from "./HelpLink.module.css";
import { Icon } from "./Icon";

/** The ? in a page's header: the help for the page it's on. */
export function HelpLink() {
  const { pathname } = useLocation();
  return (
    <Link
      to={`/help?for=${encodeURIComponent(pathname)}`}
      aria-label="Help with this page"
      title="Help with this page"
      className={styles.help}
    >
      <Icon name="help" />
    </Link>
  );
}
