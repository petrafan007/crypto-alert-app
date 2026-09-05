import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/static/',  // Set base path to match Flask static_url_path
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom', 'axios'],
          charts: ['chart.js', 'react-chartjs-2']
        }
      }
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/api': 'http://localhost:5011', // Proxy API requests to Flask backend
      '/login': 'http://localhost:5011', // Proxy login route to Flask backend
      '/logout': 'http://localhost:5011', // Proxy logout route to Flask backend
      '/register': 'http://localhost:5011', // Proxy register route to Flask backend
      '/onboarding': 'http://localhost:5011', // Proxy onboarding route to Flask backend
      '/start-oauth': 'http://localhost:5011', // Proxy OAuth routes to Flask backend
      '/callback': 'http://localhost:5011', // Proxy OAuth callback to Flask backend
    },
  },
});
