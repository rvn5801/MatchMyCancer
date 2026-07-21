import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MatchMyCancer.ai",
  description: "AI-powered cancer trial navigation and therapy matching",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-50 min-h-screen">{children}</body>
    </html>
  );
}
