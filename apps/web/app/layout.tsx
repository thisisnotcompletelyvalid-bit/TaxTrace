import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TaxTrace Foundation",
  description: "Phases 0–3: federal tax engine and finance warehouse"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
