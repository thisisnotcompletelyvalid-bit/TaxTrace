import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "TaxTrace",
  description: "Auditable federal, Florida, and Gainesville tax attribution with explicit modeled-tax boundaries"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <nav style={{ maxWidth: "1100px", margin: "0 auto", padding: "1rem 1.25rem 0", display: "flex", gap: "1rem" }}>
          <Link href="/">Federal receipt</Link>
          <Link href="/florida">Florida + Gainesville</Link>
        </nav>
        {children}
      </body>
    </html>
  );
}
