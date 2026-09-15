import { Inter } from "next/font/google";
import { Metadata } from "next";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Resume | Igor Souza",
  description: "Igor Souza's resume",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="light">
      <body className={`flex min-h-[100vh] flex-col ${inter.className}`}>
        {children}
      </body>
    </html>
  );
}
