import type { Metadata, Viewport } from "next";
import { Libre_Baskerville } from "next/font/google";

import "@/styles/globals.css";


const display = Libre_Baskerville({
  subsets: ["latin"],
  weight: ["400", "700"],
  style: ["normal", "italic"],
  variable: "--display",
});


export const metadata: Metadata = {
  title: "Email checker",
  description: "Find and check professional email addresses.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0d0f0f",
};

// Runs before paint so the sign-in screen and the app share one theme, with no flash.
const THEME_SCRIPT = `try {
  var saved = localStorage.getItem("email-checker-theme");
  var dark = saved ? saved === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "dark" : "light";
} catch (e) {}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} /></head>
      <body className={display.variable}>{children}</body>
    </html>
  );
}
