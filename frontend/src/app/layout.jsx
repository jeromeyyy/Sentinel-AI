import { Inter } from 'next/font/google';
import { AuthProvider } from '@/components/GoogleLogin';
import { ThemeProvider } from '@/contexts/ThemeContext';
import { ToastProvider } from '@/components/ui/Toast';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
});

export const metadata = {
  title: 'SentinelAI',
  description: 'SentinelAI - AI-Powered School Safety Monitoring System',
  icons: {
    icon: '/favicon.svg',
    apple: '/favicon.svg',
  },
};

export const viewport = {
  themeColor: '#0a0e14',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`dark ${inter.className}`}>
      <body className="antialiased">
        <AuthProvider>
          <ThemeProvider>
            <ToastProvider>
              {children}
            </ToastProvider>
          </ThemeProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
