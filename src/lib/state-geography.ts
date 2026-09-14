const ALIASES: Record<string, string> = {
  orissa: "odisha",
  uttaranchal: "uttarakhand",
  "nct of delhi": "delhi",
  "jammu & kashmir": "jammu and kashmir",
  "andaman & nicobar islands": "andaman and nicobar islands",
  "andaman and nicobar": "andaman and nicobar islands",
  pondicherry: "puducherry",
};

export function normalizeState(name: string) {
  const key = name.trim().toLowerCase();
  return ALIASES[key] ?? key;
}
