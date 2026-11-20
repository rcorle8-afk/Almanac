import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  return {
    plugins: [react()],
    server: {
      proxy: { "/ws": { target: `http://127.0.0.1:${env.PORT ?? 8000}`, ws: true } },
    },
  };
});
