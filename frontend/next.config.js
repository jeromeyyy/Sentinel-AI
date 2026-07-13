/** @type {import('next').NextConfig} */
const path = require('path');
const dotenv = require('dotenv');

// Load environment variables from root .env (centralized config)
const rootEnvPath = path.resolve(__dirname, '..', '.env');
dotenv.config({ path: rootEnvPath });

const nextConfig = {
  reactStrictMode: true,
  // Allow images from the backend domain
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '**.onrender.com',
      },
      {
        protocol: 'http',
        hostname: 'localhost',
      },
    ],
  },
  // Expose env vars to the browser (NEXT_PUBLIC_* vars from root .env)
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || process.env.BACKEND_URL?.replace('/event', '') || 'http://localhost:8000',
    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL || process.env.ALERT_WS_URL || 'ws://localhost:8000/ws/alerts',
  },
}

module.exports = nextConfig
