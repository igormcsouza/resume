import { readFileSync } from "fs";
import { describe, expect, it } from "vitest";

import { LANGS, cv, formatDate, formatDateRange, getCv, isLang, labels, splitBold, t } from "./cv";
import type { Cv, Localized } from "./cv";
import { ROLES, RoleSlug } from "./roles";

function expectLocalized(value: Localized, path: string) {
  if (typeof value === "string") return;
  for (const lang of LANGS) {
    expect(value[lang], `${path}.${lang}`).toBeTruthy();
  }
}

const CV_FILES = ["cv.json", ...ROLES.map((role) => `cv.${role.slug}.json`)];

describe.each(CV_FILES)("%s", (file) => {
  it("is valid, parseable JSON", () => {
    const raw = readFileSync(new URL(`./${file}`, import.meta.url), "utf-8");
    expect(() => JSON.parse(raw)).not.toThrow();
  });

  const slug = file.replace(/^cv\.|\.json$/g, "") as RoleSlug;
  const data: Cv = file === "cv.json" ? cv : getCv(slug);

  it("has required top-level sections", () => {
    for (const key of ["basics", "profile", "work", "education", "projects", "courses", "skills", "languages"]) {
      expect(data, key).toHaveProperty(key);
    }
  });

  it("has localized text with both en and pt for basics/profile", () => {
    expectLocalized(data.basics.label, "basics.label");
    expectLocalized(data.basics.location, "basics.location");
    if (Array.isArray(data.profile)) {
      expect(data.profile.length).toBeGreaterThan(0);
      data.profile.forEach((item, i) => {
        expectLocalized(item, `profile[${i}]`);
        for (const lang of LANGS) {
          const markers = t(item, lang).split("**").length - 1;
          expect(markers % 2, `profile[${i}].${lang} has unbalanced ** markers`).toBe(0);
        }
      });
    } else {
      expectLocalized(data.profile, "profile");
    }
  });

  it("has consistent work entries", () => {
    expect(data.work.length).toBeGreaterThan(0);
    for (const job of data.work) {
      expect(job.company).toBeTruthy();
      expect(job.startDate).toBeTruthy();
      expectLocalized(job.position, `work[${job.company}].position`);
      expect(job.highlights.length).toBeGreaterThan(0);
      job.highlights.forEach((h, i) => expectLocalized(h, `work[${job.company}].highlights[${i}]`));
    }
  });

  it("has consistent project entries", () => {
    expect(data.projects.length).toBeGreaterThan(0);
    for (const project of data.projects) {
      expect(project.name).toBeTruthy();
      expect(Array.isArray(project.stack)).toBe(true);
      expectLocalized(project.description, `projects[${project.name}].description`);
    }
  });

  it("has consistent skill groups", () => {
    for (const group of data.skills) {
      expectLocalized(group.category, "skills.category");
      expect(group.items.length).toBeGreaterThan(0);
    }
  });

  it("has education with institution and dates", () => {
    expect(data.education.length).toBeGreaterThan(0);
    for (const education of data.education) {
      expect(education.institution).toBeTruthy();
      expect(education.startDate).toBeTruthy();
      expect(education.endDate).toBeTruthy();
    }
  });

  it("lists pytest and Agile/Scrum in skills", () => {
    const items = data.skills.flatMap((group) => group.items);
    for (const skill of ["pytest", "Agile", "Scrum"]) {
      expect(items, skill).toContain(skill);
    }
  });

  it("has consistent languages", () => {
    for (const language of data.languages) {
      expectLocalized(language.name, "languages.name");
      expectLocalized(language.level, "languages.level");
    }
  });
});

describe("isLang", () => {
  it("accepts known languages", () => {
    expect(isLang("en")).toBe(true);
    expect(isLang("pt")).toBe(true);
  });

  it("rejects unknown languages", () => {
    expect(isLang("fr")).toBe(false);
  });
});

describe("t", () => {
  it("returns plain strings unchanged", () => {
    expect(t("Docker", "en")).toBe("Docker");
  });

  it("resolves the localized value for the given language", () => {
    const value = { en: "Hello", pt: "Olá" };
    expect(t(value, "en")).toBe("Hello");
    expect(t(value, "pt")).toBe("Olá");
  });
});

describe("splitBold", () => {
  it("returns plain text as a single segment", () => {
    expect(splitBold("Plain bullet text")).toEqual([{ text: "Plain bullet text", bold: false }]);
  });

  it("marks the text between ** markers as bold", () => {
    expect(splitBold("Builds **backend** and **AI** features")).toEqual([
      { text: "Builds ", bold: false },
      { text: "backend", bold: true },
      { text: " and ", bold: false },
      { text: "AI", bold: true },
      { text: " features", bold: false },
    ]);
  });

  it("handles bold at the start and end of the text", () => {
    expect(splitBold("**Agile** teams use **Scrum**")).toEqual([
      { text: "Agile", bold: true },
      { text: " teams use ", bold: false },
      { text: "Scrum", bold: true },
    ]);
  });
});

describe("formatDate", () => {
  it("formats year-month as month name + year", () => {
    expect(formatDate("2022-05", "en")).toBe("May 2022");
    expect(formatDate("2022-05", "pt")).toBe("Maio 2022");
  });

  it("returns the year unchanged when no month is present", () => {
    expect(formatDate("2022", "en")).toBe("2022");
  });
});

describe("formatDateRange", () => {
  it("uses the 'present' label when there is no end date", () => {
    expect(formatDateRange("2022-05", null, "en")).toBe(`May 2022 – ${labels.present.en}`);
  });

  it("formats a closed range", () => {
    expect(formatDateRange("2021-12", "2022-05", "en")).toBe("December 2021 – May 2022");
  });

  it("returns an empty string when both dates are missing", () => {
    expect(formatDateRange(null, null, "en")).toBe("");
  });
});
