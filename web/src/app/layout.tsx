import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tracker Portfolio",
  description: "Personal portfolio dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
