import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router";
import styles from "./Button.module.css";

type Variant = "primary" | "secondary" | "ghost";

function classes(variant: Variant, block: boolean, extra?: string) {
  return [styles.button, styles[variant], block && styles.block, extra].filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  block?: boolean;
  children: ReactNode;
};

export function Button({ variant = "primary", block = false, className, ...props }: ButtonProps) {
  return <button type="button" className={classes(variant, block, className)} {...props} />;
}

type ButtonLinkProps = LinkProps & { variant?: Variant; block?: boolean };

/** A link that looks like a button, for actions that navigate. */
export function ButtonLink({ variant = "primary", block = false, className, ...props }: ButtonLinkProps) {
  return <Link className={classes(variant, block, className as string | undefined)} {...props} />;
}
