import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "EduLink Admin",
  description: "EduLink Management Panel",
  manifest: "/manifest.json",
  themeColor: "#7C3AED",
  viewport: "width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <head>
        <link rel="icon" href="/favicon.ico" />
        <link rel="apple-touch-icon" href="/icon-192.png" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="EduLink" />
        <meta name="mobile-web-app-capable" content="yes" />
      </head>
      <body className={inter.className}>
        {children}
        <script dangerouslySetInnerHTML={{ __html: `
          if ('serviceWorker' in navigator) {
            window.addEventListener('load', () => {
              navigator.serviceWorker.register('/sw.js').then(reg => {
                reg.update();
                reg.addEventListener('updatefound', () => {
                  const nw = reg.installing;
                  if (!nw) return;
                  nw.addEventListener('statechange', () => {
                    if (nw.state === 'activated' && navigator.serviceWorker.controller) {
                      location.reload();
                    }
                  });
                });
              });
            });
          }
        `}} />
      </body>
    </html>
  );
}
