/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Required by the Docker images, which copy .next/standalone + server.js.
  output: "standalone",
};

module.exports = nextConfig;
