"use client"

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Download, Github, Globe, Linkedin, Mail, MapPin, Phone } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BrazilIcon, EnglandIcon } from "@/components/svg";
import { Cv, Lang, Localized, formatDateRange, labels, profileHtml, t } from "@/lib/cv";
import { GENERAL_LABEL, ROLES, RoleSlug } from "@/lib/roles";

function getProfileIcon(network: string) {
  switch (network) {
    case "linkedin":
      return Linkedin;
    case "github":
      return Github;
    default:
      return Globe;
  }
}

function Banner({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="bg-secondary px-4 py-2 text-sm font-bold uppercase tracking-widest text-secondary-foreground break-inside-avoid break-after-avoid">
      {children}
    </h2>
  );
}

// Entries with at least this many bullets may split across printed pages.
const BREAKABLE_MIN_ITEMS = 3;

function Entry({ aside, breakable, children }: { aside?: React.ReactNode, breakable?: boolean, children: React.ReactNode }) {
  // Keeping a long entry whole pushes it to the next page and leaves most of
  // the current one blank, so breakable entries split between their bullets.
  return (
    <div className={`grid gap-2 sm:grid-cols-[160px_1fr] sm:gap-x-6 ${breakable ? "" : "break-inside-avoid"}`}>
      <div className="text-sm text-muted-foreground">{aside}</div>
      <div>{children}</div>
    </div>
  );
}

export default function CvView({ lang, cv, role }: { lang: Lang; cv: Cv; role?: RoleSlug }) {
  const otherLang: Lang = lang === "en" ? "pt" : "en";
  const loc = (value: Localized) => t(value, lang);
  const router = useRouter();

  function handleExportPdf() {
    const originalTitle = document.title;
    const pdfFilename = role ? `igor_souza_${role}_resume_${lang}` : `igor_souza_resume_${lang}`;
    document.title = pdfFilename;
    const restoreTitle = () => {
      document.title = originalTitle;
      window.removeEventListener("afterprint", restoreTitle);
    };
    window.addEventListener("afterprint", restoreTitle);
    window.print();
  }

  return (
    <div className="mx-auto my-10 flex w-full max-w-3xl flex-col gap-4 px-4 print:my-0 print:max-w-none print:px-0 sm:px-0">

      {/* Desktop/tablet toolbar (unchanged) */}
      <div className="hidden items-center justify-between gap-4 print:hidden sm:flex">
        <div className="flex items-center gap-2">
          <Button variant="outline" asChild>
            <a href="https://igormcsouza.github.io" className="flex items-center gap-2">
              <ArrowLeft size={16} />
              {labels.portfolio[lang]}
            </a>
          </Button>
          <Button variant="outline" asChild>
            <Link href={`/${otherLang}`} className="flex items-center gap-2">
              {otherLang === "pt" ? <BrazilIcon className="text-xl" /> : <EnglandIcon className="text-xl" />}
              {labels.otherLanguage[lang]}
            </Link>
          </Button>
          <Select
            value={role ?? "general"}
            onValueChange={(value) => router.push(value === "general" ? `/${lang}` : `/${lang}/${value}`)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="general">{GENERAL_LABEL[lang]}</SelectItem>
              {ROLES.map((r) => (
                <SelectItem key={r.slug} value={r.slug}>{r.label[lang]}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          onClick={handleExportPdf}
          className="flex items-center gap-2 rounded-full bg-green-600 text-white hover:bg-green-700 print:bg-black"
        >
          <Download size={16} />
          {labels.exportPdf[lang]}
        </Button>
      </div>

      {/* Mobile toolbar */}
      <div className="flex flex-col gap-4 border-b pb-4 print:hidden sm:hidden">
        <div className="flex items-start justify-between gap-4">
          <a
            href="https://igormcsouza.github.io"
            className="flex items-center gap-3"
          >
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-secondary">
              <ArrowLeft size={18} />
            </span>
            <span>
              <span className="block font-bold leading-tight">{labels.portfolio[lang]}</span>
              <span className="block text-sm text-muted-foreground">{labels.portfolioSubtitle[lang]}</span>
            </span>
          </a>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href={`/${otherLang}`}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-full border px-2 py-2 text-xs font-medium"
          >
            {otherLang === "pt" ? <BrazilIcon className="text-base" /> : <EnglandIcon className="text-base" />}
            <span className="truncate">{labels.otherLanguage[lang]}</span>
          </Link>
          <Select
            value={role ?? "general"}
            onValueChange={(value) => router.push(value === "general" ? `/${lang}` : `/${lang}/${value}`)}
          >
            <SelectTrigger className="flex-1 rounded-full text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="general">{GENERAL_LABEL[lang]}</SelectItem>
              {ROLES.map((r) => (
                <SelectItem key={r.slug} value={r.slug}>{r.label[lang]}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            onClick={handleExportPdf}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-full bg-green-600 px-2 text-xs text-white hover:bg-green-700 print:bg-black"
          >
            <Download size={14} />
            <span className="truncate">{labels.exportPdf[lang]}</span>
          </Button>
        </div>
      </div>

      <article className="flex flex-col gap-6 rounded-md border bg-card p-8 text-card-foreground shadow-lg sm:p-12 print:gap-5 print:rounded-none print:border-none print:p-0 print:shadow-none">

        {/* Header: name on the left, contacts on the right */}
        <header className="flex flex-wrap justify-between gap-6">
          <div>
            <h1 className="max-w-72 text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">
              {cv.basics.name}
            </h1>
            <p className="mt-3 text-muted-foreground">{loc(cv.basics.label)}</p>
          </div>
          <ul className="flex flex-col gap-2 text-sm">
            <li className="flex items-center gap-2">
              <Phone size={14} className="shrink-0 text-muted-foreground" />{cv.basics.phone}
            </li>
            <li className="flex items-center gap-2">
              <Mail size={14} className="shrink-0 text-muted-foreground" />
              <a href={`mailto:${cv.basics.email}`}>{cv.basics.email}</a>
            </li>
            <li className="flex items-center gap-2">
              <MapPin size={14} className="shrink-0 text-muted-foreground" />{loc(cv.basics.location)}
            </li>
            {cv.basics.profiles.map((profile) => {
              const Icon = getProfileIcon(profile.network);
              return (
                <li key={profile.network} className="flex items-center gap-2">
                  <Icon size={14} className="shrink-0 text-muted-foreground" />
                  <a href={profile.url} target="_blank" rel="noreferrer">{profile.label}</a>
                </li>
              );
            })}
          </ul>
        </header>

        {cv.profile.length > 0 && (
          <section className="flex flex-col gap-3">
            <Banner>{labels.profile[lang]}</Banner>
            <ul className="flex list-disc flex-col gap-1 pl-4 text-sm leading-relaxed text-foreground/80 [&_b]:font-semibold [&_b]:text-foreground [&_strong]:font-semibold [&_strong]:text-foreground">
              {cv.profile.map((item, index) => (
                // profileHtml escapes everything except a few inline formatting tags.
                <li key={index} className="break-inside-avoid" dangerouslySetInnerHTML={{ __html: profileHtml(loc(item)) }} />
              ))}
            </ul>
          </section>
        )}

        {cv.work.length > 0 && (
          <section className="flex flex-col gap-4">
            <Banner>{labels.employmentHistory[lang]}</Banner>
            {cv.work.map((job) => (
              <Entry
                key={`${job.company}-${job.startDate}`}
                breakable={job.highlights.length >= BREAKABLE_MIN_ITEMS}
                aside={
                  <>
                    {job.url
                      ? <a href={job.url} target="_blank" rel="noreferrer" className="block font-semibold text-foreground/90">{job.company}</a>
                      : <span className="block font-semibold text-foreground/90">{job.company}</span>}
                    <span className="tabular-nums">{formatDateRange(job.startDate, job.endDate, lang)}</span>
                  </>
                }
              >
                <h3 className="mb-1.5 text-base font-bold break-after-avoid">{loc(job.position)}</h3>
                <ul className="flex list-disc flex-col gap-1 pl-4 text-sm text-foreground/80">
                  {job.highlights.map((highlight, index) => (
                    <li key={index} className="break-inside-avoid">{loc(highlight)}</li>
                  ))}
                </ul>
                {job.technologies.length > 0 && (
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    <span className="font-semibold text-foreground/80">{labels.technologies[lang]}:</span>{" "}
                    {job.technologies.join(" · ")}
                  </p>
                )}
              </Entry>
            ))}
          </section>
        )}

        {cv.projects.length > 0 && (
          <section className="flex flex-col gap-4">
            <Banner>{labels.projects[lang]}</Banner>
            {cv.projects.map((project) => (
              <Entry
                key={project.name}
                aside={<span className="block font-semibold text-foreground/90">{project.name}</span>}
              >
                <p className="text-sm text-foreground/80">{loc(project.description)}</p>
                {project.stack.length > 0 && (
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    <span className="font-semibold text-foreground/80">{labels.stack[lang]}:</span>{" "}
                    {project.stack.join(" · ")}
                  </p>
                )}
              </Entry>
            ))}
          </section>
        )}

        {cv.education.length > 0 && (
          <section className="flex flex-col gap-3">
            <Banner>{labels.education[lang]}</Banner>
            {cv.education.map((education, index) => (
              <Entry
                key={index}
                aside={
                  <>
                    {education.institution && <span className="block font-semibold text-foreground/90">{education.institution}</span>}
                    <span className="tabular-nums">{formatDateRange(education.startDate, education.endDate, lang)}</span>
                  </>
                }
              >
                <h3 className="text-base font-bold">{loc(education.degree)}</h3>
              </Entry>
            ))}
          </section>
        )}

        {cv.courses.length > 0 && (
          <section className="flex flex-col gap-3">
            <Banner>{labels.courses[lang]}</Banner>
            <Entry breakable={cv.courses.length >= BREAKABLE_MIN_ITEMS}>
              <ul className="flex list-disc flex-col gap-1 pl-4 text-sm text-foreground/80">
                {cv.courses.map((course, index) => (
                  <li key={index} className="break-inside-avoid">{loc(course)}</li>
                ))}
              </ul>
            </Entry>
          </section>
        )}

        {cv.skills.length > 0 && (
          <section className="grid gap-2 sm:grid-cols-[160px_1fr] sm:gap-x-6 break-inside-avoid">
            <h2 className="self-start bg-secondary px-4 py-2 text-sm font-bold uppercase tracking-widest text-secondary-foreground">
              {labels.skills[lang]}
            </h2>
            <div className="flex flex-col gap-2">
              {cv.skills.map((group, index) => (
                <p key={index} className="text-sm text-muted-foreground">
                  <span className="font-bold text-foreground">{loc(group.category)}:</span>{" "}
                  {group.items.join(", ")}
                </p>
              ))}
            </div>
          </section>
        )}

        {cv.languages.length > 0 && (
          <section className="grid gap-2 sm:grid-cols-[160px_1fr] sm:gap-x-6 break-inside-avoid">
            <h2 className="self-start bg-secondary px-4 py-2 text-sm font-bold uppercase tracking-widest text-secondary-foreground">
              {labels.languages[lang]}
            </h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {cv.languages.map((language, index) => (
                <div key={index}>
                  <h3 className="mb-1.5 text-sm font-bold">{loc(language.name)}</h3>
                  <p className="text-sm text-muted-foreground">{loc(language.level)}</p>
                </div>
              ))}
            </div>
          </section>
        )}

      </article>
    </div>
  );
}
