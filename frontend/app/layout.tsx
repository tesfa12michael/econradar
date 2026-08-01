import type { Metadata } from 'next';

import './globals.css';

export const metadata: Metadata = {
  title: 'EconRadar — AI-native economic intelligence',
  description:
    'Live World Bank / IMF / FRED / BIS data with zero-shot forecasting, VLM chart interpretation, and grounded economic Q&A. Free and open source.',
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
