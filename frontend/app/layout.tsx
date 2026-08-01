import type { Metadata, Viewport } from 'next';
import { Geist, JetBrains_Mono } from 'next/font/google';

import { Atmosphere } from '@/components/atmosphere/Atmosphere';
import { PointerProvider } from '@/components/atmosphere/PointerField';

import './globals.css';

/* Both faces were named in the token file and never actually loaded, so every
 * page has been rendering in system-ui since Phase 2.
 *
 * Geist rather than the Inter that docs/designsystem.md names: the reasoning
 * there is "shadcn/ui is designed around it", which stopped applying when the
 * component library was dropped in decision #26, and Inter is now the default
 * face of every generated interface on the web. Geist is the same class of
 * neutral grotesque with a tighter, more mechanical drawing that suits an
 * instrument. Recorded as a deviation in architecture.md decision #46.
 *
 * JetBrains Mono is exactly as specified — and promoted. It sets every figure,
 * date, country code, coverage count and axis label in the product, not just
 * the numbers in tables. Official statistics are published in fixed-width
 * columns; letting the mono carry all of the measured content and the sans
 * carry only prose is what gives the pages their voice.
 */
const geist = Geist({
  subsets: ['latin'],
  variable: '--font-geist',
  display: 'swap',
});

const jetbrains = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains',
  display: 'swap',
});

export const metadata: Metadata = {
  title: {
    default: 'EconRadar — economic data you can check',
    template: '%s — EconRadar',
  },
  description:
    'Live World Bank, IMF, FRED and BIS series with zero-shot forecasting, AI chart reading, and an agent that queries the database instead of guessing. Every figure carries its source and its date.',
};

export const viewport: Viewport = {
  themeColor: '#0a0f1e',
  colorScheme: 'dark',
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${geist.variable} ${jetbrains.variable}`}>
      <body className="min-h-dvh antialiased">
        <a
          href="#main"
          className="sr-only rounded-md bg-signal px-4 py-2 font-medium text-signal-ink focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60]"
        >
          Skip to content
        </a>
        <PointerProvider>
          <Atmosphere />
          <div className="relative" style={{ zIndex: 'var(--z-raised)' }}>
            {children}
          </div>
        </PointerProvider>
      </body>
    </html>
  );
}
