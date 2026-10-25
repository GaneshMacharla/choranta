import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

// Component tests run in jsdom against mocked API services; nothing reaches the backend
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }),
);
