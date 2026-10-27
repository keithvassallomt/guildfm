import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useParams, useSearchParams } from "react-router";
import { api, type Permission, type Role } from "../api";
import { useAuth } from "../auth/AuthProvider";
import { ButtonLink } from "../components/Button";
import { Icon } from "../components/Icon";
import { SegmentedControl } from "../components/SegmentedControl";
import { useWide } from "../components/useWide";
import page from "../pages/Page.module.css";
import h from "./Help.module.css";
import { Markdown, sections } from "./Markdown";
import type { Reading } from "./Shot";
import {
  AREAS,
  type Can,
  canRead,
  readable,
  slug,
  type Topic,
  TOPICS,
  topicsFor,
  words,
} from "./topics";

const ROLES: Role[] = ["user", "curator", "admin"];
const ROLE_NAMES: Record<Role, string> = { user: "User", curator: "Curator", admin: "Admin" };
const READ_AS = "guildfm-help-as";

/** Whose eyes the help is read through: your own, or for admins and curators, a role below
 *  theirs, for explaining things to people. Signed out, a guest's, who reads the getting-started
 *  topics. */
type Reader = { role: Reading; can: Can; guest: boolean };

function useReader(): { reader: Reader; readAs: ReactNode } {
  const { me, can } = useAuth();
  const own = me?.role ?? null;
  const choices = own ? ROLES.slice(0, ROLES.indexOf(own) + 1) : [];
  const [as, setAs] = useState<Role | null>(() => {
    try {
      const saved = sessionStorage.getItem(READ_AS) as Role | null;
      return saved && choices.includes(saved) ? saved : own;
    } catch {
      return own;
    }
  });
  const [roles, setRoles] = useState<Record<Role, Permission[]> | null>(null);
  useEffect(() => {
    if (own && as !== own && !roles) {
      api<Record<Role, Permission[]>>("GET", "/roles")
        .then(setRoles)
        .catch(() => setAs(own));
    }
  }, [as, own, roles]);

  const choose = (role: Role) => {
    setAs(role);
    try {
      sessionStorage.setItem(READ_AS, role);
    } catch {
      // Not remembered, which is fine.
    }
  };

  if (!own) return { reader: { role: "guest", can: () => false, guest: true }, readAs: null };
  const role = as && choices.includes(as) ? as : own;
  const reader: Reader =
    role === own || !roles
      ? { role: own, can, guest: false }
      : { role, can: (p) => roles[role].includes(p), guest: false };
  const readAs =
    choices.length > 1 ? (
      <div className={h.readAs}>
        <span className={h.readAsLabel}>Read as</span>
        <SegmentedControl
          label="Read the help as"
          options={choices.map((choice) => ({ value: choice, label: ROLE_NAMES[choice] }))}
          value={reader.role as Role}
          onChange={choose}
        />
      </div>
    ) : null;
  return { reader, readAs };
}

/** The help: every topic the reader can see, by area, and each topic on its own page. */
export default function Help() {
  const { reader, readAs } = useReader();
  return (
    <Routes>
      <Route index element={<HelpHome reader={reader} readAs={readAs} />} />
      <Route path=":id" element={<TopicPage reader={reader} readAs={readAs} />} />
      <Route path="*" element={<Navigate to="/help" replace />} />
    </Routes>
  );
}

type PageProps = { reader: Reader; readAs: ReactNode };

const INTRO: Record<Reading, string> = {
  guest: "How GuildFM works, and how to get started with it, step by step.",
  user: "How to request songs, vote on the queue and set up your profile, step by step.",
  curator:
    "How to request and vote, run the music, and build playlists, radio stations and line-ups, step by step.",
  admin: "Everything GuildFM does, from requesting a song to looking after the whole system, step by step.",
};

function HelpHome({ reader, readAs }: PageProps) {
  const [params] = useSearchParams();
  const [query, setQuery] = useState("");
  const visible = TOPICS.filter((topic) => canRead(topic, reader.can, reader.guest));
  const forPage = params.get("for");
  const here = forPage ? topicsFor(visible, forPage) : [];
  const found = useMemo(() => search(visible, query, reader.can), [visible, query, reader.can]);

  // A page with one topic opens it straight away.
  if (here.length === 1) return <Navigate to={`/help/${here[0].id}`} replace />;

  return (
    <div className={`${page.page} ${h.home}`}>
      <header className={page.header}>
        <h1 className={page.title}>Help</h1>
        {reader.guest && (
          <ButtonLink variant="secondary" to="/">
            Sign in
          </ButtonLink>
        )}
      </header>
      {readAs}
      <p className={h.intro}>{INTRO[reader.role]}</p>
      <label className={h.search}>
        <Icon name="search" size={20} />
        <span className="visually-hidden">Search the help</span>
        <input
          type="search"
          value={query}
          placeholder="Search the help"
          autoComplete="off"
          enterKeyHint="search"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>

      {found ? (
        found.length > 0 ? (
          <TopicList topics={found} />
        ) : (
          <p className={page.muted}>Nothing in the help matches that. Try other words.</p>
        )
      ) : (
        <>
          {here.length > 1 && (
            <section className={page.section} aria-labelledby="this-page">
              <h2 id="this-page" className={h.areaTitle}>
                Help with this page
              </h2>
              <TopicList topics={here} />
            </section>
          )}
          <div className={h.areas}>
            {AREAS.map((area) => {
              const topics = visible.filter((topic) => topic.area === area.id);
              if (topics.length === 0) return null;
              return (
                <section key={area.id} className={page.section} aria-labelledby={`area-${area.id}`}>
                  <h2 id={`area-${area.id}`} className={h.areaTitle}>
                    {area.title}
                  </h2>
                  <TopicList topics={topics} />
                </section>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

/** Topics with every word searched for in their title, summary or text, or null when nothing
 *  has been typed. */
function search(topics: Topic[], query: string, can: Can): Topic[] | null {
  const wanted = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (wanted.length === 0) return null;
  return topics.filter((topic) => {
    const text = words(`${topic.title} ${topic.summary} ${readable(topic.body, can, null)}`);
    return wanted.every((word) => text.includes(word));
  });
}

function TopicList({ topics }: { topics: Topic[] }) {
  return (
    <ul className={h.topics}>
      {topics.map((topic) => (
        <li key={topic.id}>
          <Link to={`/help/${topic.id}`} className={h.topicLink}>
            <span className={h.topicText}>
              <span className={h.topicTitle}>{topic.title}</span>
              <span className={h.topicSummary}>{topic.summary}</span>
            </span>
            <Icon name="chevronRight" size={18} />
          </Link>
        </li>
      ))}
    </ul>
  );
}

function TopicPage({ reader, readAs }: PageProps) {
  const { id } = useParams();
  const topic = TOPICS.find((each) => each.id === id);
  const visible = TOPICS.filter((each) => canRead(each, reader.can, reader.guest));
  const wide = useWide();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [id]);

  if (!topic || !canRead(topic, reader.can, reader.guest)) return <Navigate to="/help" replace />;
  const text = readable(topic.body, reader.can, wide ? "desktop" : "phone");
  const parts = sections(text);
  const area = AREAS.find((each) => each.id === topic.area)!;
  const more = visible.filter((each) => each.area === topic.area && each.id !== topic.id);

  return (
    <div className={page.page}>
      <header className={page.header}>
        <div className={page.headerStart}>
          <Link to="/help" aria-label="All help" className={page.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={page.title}>{topic.title}</h1>
        </div>
      </header>
      {readAs}
      <div className={h.layout}>
        <nav className={h.contents} aria-label="Help topics">
          <Link to="/help" className={h.contentsHome}>
            All help
          </Link>
          {AREAS.map((each) => {
            const topics = visible.filter((t) => t.area === each.id);
            if (topics.length === 0) return null;
            return (
              <div key={each.id} className={h.contentsArea}>
                <span className={h.contentsTitle}>{each.title}</span>
                {topics.map((t) => (
                  <NavLink
                    key={t.id}
                    to={`/help/${t.id}`}
                    className={({ isActive }) => `${h.contentsLink} ${isActive ? h.current : ""}`}
                  >
                    {t.title}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>

        <article className={h.article}>
          <p className={h.summary}>{topic.summary}</p>
          {parts.length >= 3 && (
            <nav className={h.onThisPage} aria-label="On this page">
              <span className={h.onThisPageTitle}>On this page</span>
              <ul>
                {parts.map((part) => (
                  <li key={part}>
                    <a href={`#${slug(part)}`}>{part}</a>
                  </li>
                ))}
              </ul>
            </nav>
          )}
          <Markdown text={text} role={reader.role} />
          {more.length > 0 && (
            <section className={h.more} aria-labelledby="more">
              <h2 id="more" className={h.areaTitle}>
                More in {area.title}
              </h2>
              <TopicList topics={more} />
            </section>
          )}
        </article>
      </div>
    </div>
  );
}
