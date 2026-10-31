import { Metadata } from "next";
import { notFound } from "next/navigation";

import LiveCv from "@/components/live-cv";
import { LANGS, cv, isLang } from "@/lib/cv";

export const dynamicParams = false;

export function generateStaticParams() {
  return LANGS.map((lang) => ({ lang }));
}

export async function generateMetadata({ params }: { params: Promise<{ lang: string }> }): Promise<Metadata> {
  const { lang } = await params;
  const description = isLang(lang) && lang === "pt"
    ? `Currículo de ${cv.basics.name}`
    : `Resume of ${cv.basics.name}`;
  return {
    title: `${cv.basics.name} | Resume`,
    description,
  };
}

export default async function CvPage({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  if (!isLang(lang)) notFound();
  return <LiveCv lang={lang} initial={cv} />;
}
