import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // A second lockfile sits at the repository root, so Next infers the workspace
  // root one level up and warns. The app is self-contained in this directory.
  outputFileTracingRoot: __dirname,
  experimental: {
    // Phosphor's entry point is a barrel over several thousand icons. Without
    // this the whole family is pulled into any chunk that imports one glyph.
    optimizePackageImports: ['@phosphor-icons/react'],
  },
};

export default nextConfig;
