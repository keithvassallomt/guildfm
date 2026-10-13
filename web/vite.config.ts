import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs on :8000 and Vite on :5173. Vite forwards API and live traffic,
// so phones on the office network can open http://<this machine>:5173.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
