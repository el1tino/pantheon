import type { Metadata } from "next";
import { Geist_Mono, Hanken_Grotesk } from "next/font/google";
import { APP_NAME, CAP_A_GROUP } from "@/lib/app";
import "./globals.css";

// One typeface for the whole interface; monospace only for code, file names and the core counters.
const ui = Hanken_Grotesk({ variable: "--font-ui", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: APP_NAME,
  description: `${CAP_A_GROUP} of AI models that debates your goal and builds the result.`,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${ui.variable} ${geistMono.variable} font-sans antialiased`}>
        {children}
      </body>
    </html>
  );
}
