import type { PolicyBrief } from "./polaris-api";
export const BRIEF_SECTIONS: { key: keyof PolicyBrief; label: string }[] = [
  { key: "policy", label: "What the policy does" },
  { key: "benefits", label: "Likely benefits" },
  { key: "risks", label: "Main tradeoffs and risks" },
  { key: "affected", label: "Who is affected" },
  { key: "uncertainty", label: "What remains uncertain" },
  { key: "actions", label: "Recommended next actions" },
];
