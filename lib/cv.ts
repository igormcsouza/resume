import cvData from "./cv.json";
import cvBackend from "./cv.backend.json";
import cvAiMl from "./cv.ai-ml.json";
import cvDataEngineer from "./cv.data-engineer.json";
import cvDevops from "./cv.devops.json";

import type { RoleSlug } from "./roles";

export const LANGS = ["en", "pt"] as const;
export type Lang = (typeof LANGS)[number];

/**
 * A string that may or may not carry a translation. Plain strings are used
 * for content that needs no translation (names, technologies, course titles).
 */
export type Localized = string | { en: string; pt: string };

export interface CvProfileLink {
  network: string;
  label: string;
  url: string;
}

export interface CvBasics {
  name: string;
  label: Localized;
  email: string;
  phone: string;
  location: Localized;
  profiles: CvProfileLink[];
}

export interface CvWork {
  company: string;
  url?: string;
  position: Localized;
  startDate: string | null;
  endDate: string | null;
  highlights: Localized[];
  technologies: string[];
}

export interface CvEducation {
  institution: string;
  degree: Localized;
  startDate: string | null;
  endDate: string | null;
}

export interface CvSkillGroup {
  category: Localized;
  items: string[];
}

export interface CvProject {
  name: string;
  description: Localized;
  stack: string[];
}

export interface CvLanguage {
  name: Localized;
  level: Localized;
}

export interface Cv {
  basics: CvBasics;
  profile: Localized;
  work: CvWork[];
  education: CvEducation[];
  projects: CvProject[];
  courses: Localized[];
  skills: CvSkillGroup[];
  languages: CvLanguage[];
}

const CV_BY_ROLE: Record<RoleSlug, Cv> = {
  backend: cvBackend,
  "ai-ml": cvAiMl,
  "data-engineer": cvDataEngineer,
  devops: cvDevops,
};

export const cv: Cv = cvData;

/** Resolve the CV data for a given role slug, falling back to the general resume. */
export function getCv(role?: RoleSlug): Cv {
  return role ? CV_BY_ROLE[role] : cv;
}

export function isLang(value: string): value is Lang {
  return (LANGS as readonly string[]).includes(value);
}

/** Resolve a Localized value for the given language. */
export function t(value: Localized, lang: Lang): string {
  return typeof value === "string" ? value : value[lang];
}

/** UI labels for the CV template, per language. */
export const labels = {
  profile: { en: "Profile", pt: "Perfil" },
  employmentHistory: { en: "Employment History", pt: "Histórico Profissional" },
  education: { en: "Education", pt: "Formação Acadêmica" },
  projects: { en: "Projects", pt: "Projetos" },
  courses: { en: "Certifications & Courses", pt: "Certificações e Cursos" },
  stack: { en: "Stack", pt: "Stack" },
  skills: { en: "Skills", pt: "Habilidades" },
  languages: { en: "Languages", pt: "Idiomas" },
  technologies: { en: "Tech", pt: "Tecnologias" },
  exportPdf: { en: "Export PDF", pt: "Exportar PDF" },
  otherLanguage: { en: "Ver em Português", pt: "View in English" },
  portfolio: { en: "Portfolio", pt: "Portfólio" },
  present: { en: "present", pt: "atual" },
} satisfies Record<string, { en: string; pt: string }>;

const MONTHS: Record<Lang, string[]> = {
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
  pt: ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"],
};

/** Format a "YYYY-MM" (or "YYYY") date as e.g. "May 2022" / "Maio 2022". */
export function formatDate(date: string, lang: Lang): string {
  const [year, month] = date.split("-");
  if (!month) return year;
  return `${MONTHS[lang][Number(month) - 1]} ${year}`;
}

/** Format a period as e.g. "May 2022 – present" / "Maio 2022 – atual". */
export function formatDateRange(start: string | null, end: string | null, lang: Lang): string {
  if (!start && !end) return "";
  const from = start ? formatDate(start, lang) : "";
  const to = end ? formatDate(end, lang) : labels.present[lang];
  return from ? `${from} – ${to}` : to;
}
