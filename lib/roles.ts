export const ROLES = [
  { slug: "backend", label: { en: "Backend Engineer", pt: "Engenheiro Backend" } },
  { slug: "ai-ml", label: { en: "AI/ML Engineer", pt: "Engenheiro de IA/ML" } },
  { slug: "data-engineer", label: { en: "Data Engineer", pt: "Engenheiro de Dados" } },
  { slug: "devops", label: { en: "DevOps Engineer", pt: "Engenheiro DevOps" } },
] as const;

export type RoleSlug = (typeof ROLES)[number]["slug"];

export function isRole(value: string): value is RoleSlug {
  return (ROLES as readonly { slug: string }[]).some((role) => role.slug === value);
}

export const GENERAL_LABEL = { en: "General", pt: "Geral" };
