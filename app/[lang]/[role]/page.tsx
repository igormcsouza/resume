import { Metadata } from "next";
import { notFound } from "next/navigation";

import CvView from "@/components/cv-view";
import { getCv, isLang } from "@/lib/cv";
import { ROLES, isRole } from "@/lib/roles";

export const dynamicParams = false;

export function generateStaticParams() {
  return ROLES.flatMap((role) => ["en", "pt"].map((lang) => ({ lang, role: role.slug })));
}

export async function generateMetadata({ params }: { params: Promise<{ lang: string; role: string }> }): Promise<Metadata> {
  const { lang, role } = await params;
  if (!isLang(lang) || !isRole(role)) return {};
  const cv = getCv(role);
  const roleLabel = ROLES.find((r) => r.slug === role)!.label[lang];
  const description = lang === "pt"
    ? `Currículo de ${cv.basics.name}`
    : `Resume of ${cv.basics.name}`;
  return {
    title: `${cv.basics.name} | ${roleLabel} Resume`,
    description,
  };
}

export default async function CvRolePage({ params }: { params: Promise<{ lang: string; role: string }> }) {
  const { lang, role } = await params;
  if (!isLang(lang) || !isRole(role)) notFound();
  return <CvView lang={lang} cv={getCv(role)} role={role} />;
}
