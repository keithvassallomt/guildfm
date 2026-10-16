import type { CSSProperties, ReactNode } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router";
import type { Permission } from "./api";
import styles from "./App.module.css";
import { useAuth } from "./auth/AuthProvider";
import { Navigation } from "./components/Navigation";
import { QuickControls } from "./components/QuickControls";
import { LiveProvider } from "./live/LiveProvider";
import { AdminPage } from "./pages/AdminPage";
import { AnnouncementEditor } from "./pages/AnnouncementEditor";
import { AnnouncementsPage } from "./pages/AnnouncementsPage";
import { ChoosePasswordPage } from "./pages/ChoosePasswordPage";
import { LibraryPage } from "./pages/LibraryPage";
import { NowPlayingPage } from "./pages/NowPlayingPage";
import { PlaylistPage } from "./pages/PlaylistPage";
import { ProfilePage } from "./pages/ProfilePage";
import { QueuePage } from "./pages/QueuePage";
import { SearchPage } from "./pages/SearchPage";
import { SettingsPage } from "./pages/SettingsPage";
import { UsersPage } from "./pages/UsersPage";
import { WelcomePage } from "./pages/WelcomePage";

function Shell() {
  const { can } = useAuth();
  const { pathname } = useLocation();
  // Admins get quick controls everywhere but Now Playing and Admin, which have the controls.
  const quick = can("control_playback") && pathname !== "/" && pathname !== "/admin";

  return (
    <div
      className={styles.app}
      style={quick ? ({ "--fab-space": "80px" } as CSSProperties) : undefined}
    >
      <Navigation />
      <main className={styles.main}>
        <Outlet />
      </main>
      {quick && <QuickControls />}
    </div>
  );
}

/** Sends people without the permission back to Now Playing. The server enforces it too. */
function Allowed({ permission, children }: { permission: Permission; children: ReactNode }) {
  const { can } = useAuth();
  return can(permission) ? children : <Navigate to="/" replace />;
}

export function App() {
  const { me, refresh } = useAuth();

  if (me === undefined) return null;
  if (me === null) return <WelcomePage />;
  if (me.must_change_password) return <ChoosePasswordPage />;

  return (
    <LiveProvider onUnauthorised={() => refresh().catch(() => {})}>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<NowPlayingPage />} />
          <Route path="queue" element={<QueuePage />} />
          <Route path="search" element={<SearchPage />} />
          <Route
            path="library"
            element={
              <Allowed permission="switch_source">
                <LibraryPage />
              </Allowed>
            }
          />
          <Route
            path="library/playlists/:id"
            element={
              <Allowed permission="switch_source">
                <PlaylistPage />
              </Allowed>
            }
          />
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
            path="admin/settings"
            element={
              <Allowed permission="change_settings">
                <SettingsPage />
              </Allowed>
            }
          />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </LiveProvider>
  );
}
