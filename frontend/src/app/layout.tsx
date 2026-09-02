import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// Inter is the typeface the Helix Filament panels ship with.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Sentinel — Magnum Opus Consultants",
  description:
    "Server management, monitoring, and documentation. One platform, full visibility.",
};

/**
 * Applies the saved theme before first paint so there is no light-to-dark flash.
 * Runs ahead of hydration, which is why it has to be an inline script rather
 * than an effect. Falls back to the OS preference when nothing is saved, and
 * stays silent if storage is unavailable (private windows, blocked site data).
 */
const THEME_INIT = `
(function(){
  try {
    var t = localStorage.getItem('sentinel-theme');
    if (t !== 'light' && t !== 'dark') {
      t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    if (t === 'dark') document.documentElement.classList.add('dark');
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body className="min-h-full flex flex-col font-sans" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
