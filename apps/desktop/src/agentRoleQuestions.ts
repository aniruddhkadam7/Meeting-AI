// A few simple, optional, role-specific questions shown for Predefined Role
// agents — never a prompt, just plain-language context. Answers are folded
// into the agent's description/custom instructions at creation time (see
// buildPredefinedInstructions below) so the backend never needs a separate
// "role answers" concept; agent_prompt_builder.py already knows how to weave
// description + customInstructions into the role's persona.
//
// Each question is a single short prompt shown as the input's placeholder —
// no separate label line above it — so the whole set reads as a couple of
// quick fields, not a block of copy.

import { PredefinedRole } from "./types";

export interface RoleQuestion {
  key: string;
  placeholder: string;
}

const DEFAULT_QUESTIONS: RoleQuestion[] = [
  { key: "audience", placeholder: "Who do you mainly work with?" },
  { key: "focus", placeholder: "What should this agent mainly help with?" },
];

export const ROLE_QUESTIONS: Record<PredefinedRole, RoleQuestion[]> = {
  SALESPERSON: [
    { key: "audience", placeholder: "What type of customers do you sell to?" },
    { key: "products", placeholder: "What products or services do you sell?" },
    { key: "focus", placeholder: "What should this agent mainly help with?" },
  ],
  SALES_ENGINEER: [
    { key: "audience", placeholder: "Who are your technical calls usually with?" },
    { key: "products", placeholder: "What product or system do you support?" },
    { key: "focus", placeholder: "What should this agent mainly help with?" },
  ],
  CONSULTANT: [
    { key: "audience", placeholder: "Who are your clients?" },
    { key: "products", placeholder: "What kind of engagements do you run?" },
    { key: "focus", placeholder: "What should this agent mainly help with?" },
  ],
  RECRUITER: [
    { key: "audience", placeholder: "Who do you usually talk to?" },
    { key: "products", placeholder: "What roles do you typically recruit for?" },
    { key: "focus", placeholder: "What should this agent mainly help with?" },
  ],
  CUSTOMER_SUPPORT: [
    { key: "audience", placeholder: "Who are your customers?" },
    { key: "products", placeholder: "What product do you support?" },
    { key: "focus", placeholder: "What should this agent mainly help with?" },
  ],
  PROJECT_MANAGER: [
    { key: "audience", placeholder: "Who's usually in your meetings?" },
    { key: "products", placeholder: "What kind of projects do you run?" },
    { key: "focus", placeholder: "What should this agent mainly help with?" },
  ],
  BUSINESS_ANALYST: [
    { key: "audience", placeholder: "Who are your stakeholders?" },
    { key: "products", placeholder: "What area do you analyze?" },
    { key: "focus", placeholder: "What should this agent mainly help with?" },
  ],
  TECHNICAL_SUPPORT: [
    { key: "audience", placeholder: "Who are you usually helping?" },
    { key: "products", placeholder: "What product or system do you support?" },
    { key: "focus", placeholder: "What should this agent mainly help with?" },
  ],
};

export function roleQuestions(role: PredefinedRole): RoleQuestion[] {
  return ROLE_QUESTIONS[role] ?? DEFAULT_QUESTIONS;
}

/// Folds the (optional) role-question answers into a single plain-language
/// description string, the same field a Custom Agent's "What should this
/// agent help with?" box writes to. Empty answers are skipped rather than
/// written as blank clauses.
export function buildPredefinedDescription(role: PredefinedRole, answers: Record<string, string>): string | null {
  const questions = roleQuestions(role);
  const parts: string[] = [];
  for (const q of questions) {
    const value = (answers[q.key] ?? "").trim();
    if (value) parts.push(value);
  }
  return parts.length ? parts.join(". ") : null;
}
