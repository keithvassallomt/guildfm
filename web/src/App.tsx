import { type CSSProperties, lazy, type ReactNode, Suspense } from "react";
import { Navigate, Outlet, Route, Routes, useLocation, useParams, useSearchParams } from "react-router";
import type { Permission } from "./api";
import styles from "./App.module.css";
import { useAuth } from "./auth/AuthProvider";
import { MonitorBar } from "./components/MonitorBar";
import { Navigation } from "./components/Navigation";
import { QuickControls } from "./components/QuickControls";
import { LiveProvider } from "./live/LiveProvider";
import { AdminPage } from "./pages/AdminPage";
import { AnnouncementEditor } from "./pages/AnnouncementEditor";
import { AnnouncementsPage } from "./pages/AnnouncementsPage";
import { ChoosePasswordPage } from "./pages/ChoosePasswordPage";
import { JinglesPage } from "./pages/JinglesPage";
import { LineupEditor } from "./pages/LineupEditor";
import { LineupsPage } from "./pages/LineupsPage";
import { NowPlayingPage } from "./pages/NowPlayingPage";
import { PlaylistPage } from "./pages/PlaylistPage";
import { PlaylistsPage } from "./pages/PlaylistsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { QueuePage } from "./pages/QueuePage";
import { RadioPage } from "./pages/RadioPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StationEditor } from "./pages/StationEditor";
import { StatusPage } from "./pages/StatusPage";
import { UsersPage } from "./pages/UsersPage";
import { WelcomePage } from "./pages/WelcomePage";

function Shell() {
  const { can } = useAuth();
  const { pathname } = useLocation();
  // Admins get quick controls everywhere but Now Playing, which has the controls.
  const quick = can("control_playback") && pathname !== "/";

  return (
    <div
      className={styles.app}
      style={quick ? ({ "--fab-space": "80px" } as CSSProperties) : undefined}
    >
      <Navigation />
      <main className={styles.main}>
        {can("control_playback") && <MonitorBar />}
        <Outlet />
      </main>
      {quick && <QuickControls />}
    </div>
  );
}

// The help is only loaded when it's opened.
const Help = lazy(() => import("./help/Help"));

/** Where the Library's pages went when it split into Playlists and Radio. */
function OldLibrary() {
  const [params] = useSearchParams();
  return <Navigate to={params.get("tab") === "stations" ? "/radio" : "/playlists"} replace />;
}

function OldLibraryItem({ to }: { to: "playlists" | "radio" }) {
  const { id } = useParams();
  return <Navigate to={`/${to}/${id}`} replace />;
}

/** Sends people without the permission back to Now Playing. The server enforces it too. */
function Allowed({ permission, children }: { permission: Permission; children: ReactNode }) {
  const { can } = useAuth();
  return can(permission) ? children : <Navigate to="/" replace />;
}

export function App() {
  const { me, refresh } = useAuth();

  if (me === undefined) return null;
  if (me === null) {
    // Signed out, only the help's getting-started topics are open, besides signing in.
    return (
      <Routes>
        <Route
          path="help/*"
          element={
            <main className={styles.signedOut}>
              <Suspense fallback={null}>
                <Help />
              </Suspense>
            </main>
          }
        />
        <Route path="*" element={<WelcomePage />} />
      </Routes>
    );
  }
  if (me.must_change_password) return <ChoosePasswordPage />;

  return (
    <LiveProvider onUnauthorised={() => refresh().catch(() => {})}>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<NowPlayingPage />} />
          <Route path="queue" element={<QueuePage />} />
          <Route
            path="playlists"
            element={
              <Allowed permission="switch_source">
                <PlaylistsPage />
              </Allowed>
            }
          />
          <Route
            path="playlists/:id"
            element={
              <Allowed permission="switch_source">
                <PlaylistPage />
              </Allowed>
            }
          />
          <Route
            path="radio"
            element={
              <Allowed permission="switch_source">
                <RadioPage />
              </Allowed>
            }
          />
          <Route
            path="lineups"
            element={
              <Allowed permission="switch_source">
                <LineupsPage />
              </Allowed>
            }
          />
          <Route
            path="lineups/new"
            element={
              <Allowed permission="plan_lineups">
                <LineupEditor />
              </Allowed>
            }
          />
          <Route
            path="lineups/:id"
            element={
              <Allowed permission="plan_lineups">
                <LineupEditor />
              </Allowed>
            }
          />
          <Route
            path="radio/new"
            element={
              <Allowed permission="create_stations">
                <StationEditor />
              </Allowed>
            }
          />
          <Route
            path="radio/:id"
            element={
              <Allowed permission="create_stations">
                <StationEditor />
              </Allowed>
            }
          />
          {/* Old addresses: the Search page is the Queue's "Request a song" now, and the
              Library split into Playlists and Radio. */}
          <Route path="search" element={<Navigate to="/queue" replace />} />
          <Route path="library" element={<OldLibrary />} />
          <Route path="library/playlists/:id" element={<OldLibraryItem to="playlists" />} />
          <Route path="library/stations/new" element={<Navigate to="/radio/new" replace />} />
          <Route path="library/stations/:id" element={<OldLibraryItem to="radio" />} />
          <Route
            path="admin"
            element={
              <Allowed permission="control_playback">
                <AdminPage />
              </Allowed>
            }
          />
          <Route
            path="admin/users"
            element={
              <Allowed permission="manage_users">
                <UsersPage />
              </Allowed>
            }
          />
          <Route
            path="admin/announcements"
            element={
              <Allowed permission="announce">
                <AnnouncementsPage />
              </Allowed>
            }
          />
          <Route
            path="admin/announcements/new"
            element={
              <Allowed permission="announce">
                <AnnouncementEditor />
              </Allowed>
            }
          />
          <Route
            path="admin/announcements/:id"
            element={
              <Allowed permission="announce">
                <AnnouncementEditor />
              </Allowed>
            }
          />
          <Route
            path="admin/jingles"
            element={
              <Allowed permission="change_settings">
                <JinglesPage />
              </Allowed>
            }
          />
          <Route
            path="admin/status"
            element={
              <Allowed permission="change_settings">
                <StatusPage />
              </Allowed>
            }
          />
          <Route
            path="admin/settings"
            element={
              <Allowed permission="change_settings">
                <SettingsPage />
              </Allowed>
            }
          />
          <Route path="profile" element={<ProfilePage />} />
          <Route
            path="help/*"
            element={
              <Suspense fallback={null}>
                <Help />
              </Suspense>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </LiveProvider>
  );
}
