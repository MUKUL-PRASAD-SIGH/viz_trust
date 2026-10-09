import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard's sample data lives at ../docs/api_stub.json (shared with the API tests),
// so the dev server may read one level up.
export default defineConfig({
  plugins: [react()],
  server: { fs: { allow: [".."] } },
});
