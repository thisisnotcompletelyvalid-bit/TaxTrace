import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TaxTrace",
  description: "Auditable federal tax receipt, drill-down explorer, and public-finance search"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
