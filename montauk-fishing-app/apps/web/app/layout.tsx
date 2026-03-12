import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Montauk Fishing Intelligence",
  description: "Offshore fishing intelligence dashboard for Montauk.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
