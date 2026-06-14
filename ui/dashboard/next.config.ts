import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // NEXT_PUBLIC_API_URL 환경변수로 API 서버 URL 주입
  // Vercel 배포 시: NEXT_PUBLIC_API_URL=https://your-api.com
};

export default nextConfig;
