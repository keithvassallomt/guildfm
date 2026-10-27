import { Lexer, type Token, type Tokens } from "marked";
import { Fragment, type ReactNode, useMemo } from "react";
import { Link } from "react-router";
import styles from "./Help.module.css";
import { type Reading, Shot } from "./Shot";
import { slug } from "./topics";

/** A help topic's Markdown, drawn as React. `![What it shows](shot:name)` is a screenshot,
 *  `[words](topic:id)` a link to another topic, and a quote a tip. HTML isn't drawn. */
export function Markdown({ text, role }: { text: string; role: Reading }) {
  const tokens = useMemo(() => Lexer.lex(text), [text]);
  return <>{tokens.map((token, index) => block(token, index, role))}</>;
}

/** The second-level headings, for a topic's "On this page". */
export function sections(text: string): string[] {
  return Lexer.lex(text).flatMap((token) =>
    token.type === "heading" && token.depth === 2 ? [token.text] : [],
  );
}

function block(token: Token, key: number, role: Reading): ReactNode {
  switch (token.type) {
    case "heading": {
      const { depth, text, tokens } = token as Tokens.Heading;
      const content = inline(tokens, role);
      return depth <= 2 ? (
        <h2 key={key} id={slug(text)}>
          {content}
        </h2>
      ) : (
        <h3 key={key}>{content}</h3>
      );
    }
    case "paragraph": {
      const { tokens } = token as Tokens.Paragraph;
      const pictures = tokens.filter((t) => t.type === "image");
      // A screenshot on its own line stands apart, rather than inside a paragraph.
      if (pictures.length > 0 && tokens.every((t) => t.type === "image" || !t.raw.trim())) {
        return <Fragment key={key}>{pictures.map((t, i) => image(t as Tokens.Image, i, role))}</Fragment>;
      }
      return <p key={key}>{inline(tokens, role)}</p>;
    }
    case "list": {
      const list = token as Tokens.List;
      const items = list.items.map((item, i) => (
        <li key={i}>{item.tokens.map((t, j) => block(t, j, role))}</li>
      ));
      return list.ordered ? (
        <ol key={key} start={list.start === "" ? undefined : list.start} className={styles.steps}>
          {items}
        </ol>
      ) : (
        <ul key={key}>{items}</ul>
      );
    }
    case "text": {
      // Text in a list item: its words, without a paragraph round them.
      const { tokens, text } = token as Tokens.Text;
      return <Fragment key={key}>{tokens ? inline(tokens, role) : text}</Fragment>;
    }
    case "blockquote":
      return (
        <aside key={key} className={styles.tip}>
          {(token as Tokens.Blockquote).tokens.map((t, i) => block(t, i, role))}
        </aside>
      );
    case "hr":
      return <hr key={key} />;
    default:
      return null;
  }
}

function inline(tokens: Token[] | undefined, role: Reading): ReactNode {
  return tokens?.map((token, key) => {
    switch (token.type) {
      case "strong":
        return <strong key={key}>{inline((token as Tokens.Strong).tokens, role)}</strong>;
      case "em":
        return <em key={key}>{inline((token as Tokens.Em).tokens, role)}</em>;
      case "codespan":
        return <code key={key}>{(token as Tokens.Codespan).text}</code>;
      case "br":
        return <br key={key} />;
      case "link":
        return link(token as Tokens.Link, key, role);
      case "image":
        return image(token as Tokens.Image, key, role);
      case "text": {
        const text = token as Tokens.Text;
        return <Fragment key={key}>{text.tokens ? inline(text.tokens, role) : text.text}</Fragment>;
      }
      case "escape":
        return <Fragment key={key}>{(token as Tokens.Escape).text}</Fragment>;
      default:
        return <Fragment key={key}>{token.raw}</Fragment>;
    }
  });
}

function link({ href, tokens }: Tokens.Link, key: number, role: Reading) {
  const words = inline(tokens, role);
  if (href.startsWith("topic:")) {
    return (
      <Link key={key} to={`/help/${href.slice("topic:".length)}`}>
        {words}
      </Link>
    );
  }
  if (href.startsWith("/")) {
    return (
      <Link key={key} to={href}>
        {words}
      </Link>
    );
  }
  return (
    <a key={key} href={href} target="_blank" rel="noreferrer">
      {words}
    </a>
  );
}

function image({ href, text }: Tokens.Image, key: number, role: Reading) {
  if (!href.startsWith("shot:")) return null;
  return <Shot key={key} name={href.slice("shot:".length)} alt={text} role={role} />;
}
