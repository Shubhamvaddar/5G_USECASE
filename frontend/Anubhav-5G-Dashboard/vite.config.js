import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: './',
  server: { host: '0.0.0.0' },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/recharts/') || id.includes('/node_modules/victory-vendor/')) return 'charts';
          if (id.includes('/node_modules/react') || id.includes('/node_modules/scheduler/')) return 'framework';
        },
      },
    },
  },
});
