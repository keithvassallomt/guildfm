import type { ReactNode } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router";
import type { Permission } from "./api";
import styles from "./App.module.css";
import { useAuth } from "./auth/AuthProvider";
import { Navigation } from "./components/Navigation";
import { LiveProvider } from "./live/LiveProvider";
import { AdminPage } from "./pages/AdminPage";
import { ChoosePasswordPage } from "./pages/ChoosePasswordPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { ProfilePage } from "./pages/ProfilePage";
import { QueuePage } from "./pages/QueuePage";
import { UsersPage } from "./pages/UsersPage";
import { WelcomePage } from "./pages/WelcomePage";

function Shell() {
  return (
    <div className={styles.app}>
      <Navigation />
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}

/** Sends people without the permission back to the queue. The server enforces it too. */
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
          <Route index element={<QueuePage />} />
          <Route path="search" element={<PlaceholderPage title="Search" stage={4} />} />
          <Route
            path="library"
            element={
              <Allowed permission="switch_source">
                <PlaceholderPage title="Library" stage={7} />
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
          <Route path="profile" element={<ProfilePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </LiveProvider>
  );
}
