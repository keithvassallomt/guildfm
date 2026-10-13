import { Outlet, Route, Routes } from "react-router";
import styles from "./App.module.css";
import { TabBar } from "./components/TabBar";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { QueuePage } from "./pages/QueuePage";

function Shell() {
  return (
    <div className={styles.app}>
      <main>
        <Outlet />
      </main>
      <TabBar />
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<QueuePage />} />
        <Route path="search" element={<PlaceholderPage title="Search" stage={4} />} />
        <Route path="library" element={<PlaceholderPage title="Library" stage={7} />} />
        <Route path="admin" element={<PlaceholderPage title="Admin" stage={3} />} />
        <Route path="profile" element={<PlaceholderPage title="Profile" stage={2} />} />
      </Route>
    </Routes>
  );
}
