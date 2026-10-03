/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  env: {
    // NEXT_PUBLIC_* values are the only ones exposed to the browser.
    // Backend secrets (Firebase Admin, DEVICE_AUTH_SECRET) never reach this app.
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000',
    NEXT_PUBLIC_REFRESH_SECONDS: process.env.NEXT_PUBLIC_REFRESH_SECONDS ?? '15',
  },
}

export default nextConfig