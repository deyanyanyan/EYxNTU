import type { Metadata } from "next";
import "./globals.css";
import { SessionProvider } from "@/hooks/use-session";

export const metadata: Metadata = {
  title: "LMS Studio",
  description: "Turn source documents into grounded, reviewable course packages.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Apply stored theme before paint to avoid a flash. */}
        <script dangerouslySetInnerHTML={{ __html: `try{if((localStorage.getItem('lms_theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'))==='dark')document.documentElement.classList.add('dark')}catch(e){}` }} />
      </head>
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
