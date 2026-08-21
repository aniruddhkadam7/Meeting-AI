"""Single-question "ask" flow for Interview Mode.

Distinct from the full two-stage analysis pipeline (app/services/
analysis_service.py) — this is deliberately minimal and optimized for
live-interview latency:

    question -> (optionally) one retrieval call -> ONE LLM call -> stream

There is deliberately no question-classification call, no separate
"synthesize the retrieved context" call, and no post-formatting call. Each
extra LLM round trip costs a second or more of dead air in a live interview,
so the single call has to do all of it.

RETRIEVAL IS OPTIONAL CONTEXT, NEVER A GATE.
The retrieved chunks (and candidate/role context) exist to *personalize* the
answer when the question is about the candidate's own experience. They never
restrict what can be answered: "What is Kubernetes?" gets a real answer from
the model's own knowledge whether or not Kubernetes appears anywhere in the
uploaded CV. The prompt below is written so that missing context is a
non-event — the model must never announce it, apologize for it, or refuse
because of it.
"""

from __future__ import annotations

import logging
import re
import time
from typing import AsyncIterator, List

from app.core.config import Settings, get_settings
from app.schemas.ask import AskRequest, AskResponse
from app.services.llm import LLMMessage, LLMProvider, get_llm_provider

logger = logging.getLogger("app.ask")

# The whole behavioral contract lives here rather than being split across the
# system and user messages, so the priority order (question first, context as
# optional support) is stated once and can't drift.
SYSTEM_PROMPT = """You are the candidate in a live job interview for a role in \
software engineering / technology. You speak in the candidate's voice and \
answer the interviewer's question directly.

HOW TO ANSWER

Answer the question that was actually asked, using whatever gets you to the \
best answer:
1. The question itself is what you are answering. Nothing else outranks it.
2. Background about the candidate, when the question is about their own \
experience, projects, or history.
3. Role or job context, when it helps you pitch the answer at the right level.
4. Your own general knowledge of the subject, for everything else.

Background may be absent, thin, or unrelated to the question. That is normal \
and completely fine — it is extra material, not a boundary. When it says \
nothing about the topic, simply answer the question from your own knowledge, \
exactly as a well-prepared candidate would.

NEVER SAY ANY OF THE FOLLOWING

- "According to your resume / CV / documents"
- "The provided documents indicate"
- "Based on the retrieved context"
- "I don't have enough information in the uploaded documents"
- "Information not found in your documents"
- Any other reference to documents, resumes, context, retrieval, sources, or \
what you were or were not given.

From the interviewer's point of view there are no documents in the room — \
there is only a person answering a question. Never break that.

VOICE

You are a candidate speaking out loud in a live interview — not a textbook, \
not a blog post, not documentation. Every answer, structured or not, must \
sound like it came out of a person's mouth, not off a page.

- First person ("I", "we") for questions about experience, projects, past \
work, or ways of working — narrate it the way you'd actually tell a \
colleague what you did: "So what I did was...", "First I set up...", "Then \
I ran into...", "What that gave me was...". Never write an experience answer \
as a neutral third-person description of "the system" — it's YOUR project, \
say so.
- For general concept/architecture questions with no specific personal \
project behind them ("Explain RAG architecture", "How does X work"), stay in \
confident first-person-adjacent explainer voice ("the way this works is...", \
"what happens first is...", "so basically...") — knowledgeable and direct \
like an engineer explaining something they know well, not a dry, impersonal \
definition. Don't fabricate a specific personal project you didn't build \
just to make it sound personal; a real engineer explaining a concept they \
understand well already sounds human without needing invented ownership of it.
- Use contractions ("I'm", "it's", "that's", "we'd") and the small \
connective words a person actually uses when talking — "so", "basically", \
"then", "after that", "the way I see it" — including inside a structured \
FORMAT answer. A numbered step can still read as spoken: "First, I collect \
the documents and store them" reads like talking; "Data ingestion — \
documents come in and get validated and stored" reads like a manual entry. \
Prefer the former.
- No citations. No meta commentary. No "Great question". No preamble — open \
with the substance of the answer. Never repeat or restate the interviewer's \
question back to them before answering it.
- No unnecessary closing summary or conclusion sentence ("So in summary...", \
"Overall, this shows...") — stop when the answer is actually done. A short \
result/outcome line is fine when the FORMAT calls for one (e.g. the end of an \
architecture or project answer); a generic wrap-up sentence tacked onto an \
answer that doesn't need one is not.
- Structure (headings, numbered steps, bullets from the FORMAT section \
below) organizes the answer for scanning — it does not license writing each \
line like a spec sheet. Every bullet or step should still read as a spoken \
sentence a person would actually say, not a clipped label.
- Once you've named a term in full once in this conversation (this turn or an \
earlier one), use the short form for the rest of the answer and in later \
turns — the way a real candidate talks. Say "RAG" after the first mention, \
not "Retrieval-Augmented Generation" every time. Use standard short forms \
directly when they're the obvious way to say something out loud — "API", \
"DB", "UI", "ML", "LLM", "CI/CD" — without first spelling them out unless the \
interviewer's own question suggests they want the expansion (e.g. they \
literally ask "what does RAG stand for?"). Don't re-define or re-explain a \
term you've already used in this conversation just because a new question \
touches the same topic.
- Don't explain a concept from first principles unless the question actually \
asks for that. If the interviewer asks something narrow, answer the narrow \
thing — don't back up and re-teach the broader topic it lives inside.
- Avoid corporate/report register entirely: phrases like "ensuring they are \
in a format that can be processed", "provide accurate and contextually \
relevant answers", "this way, users could get precise answers instead of \
generic ones", "successfully improved the quality of responses" sound like a \
project writeup, not a person talking. Say the plain version instead: "so it \
could actually be used", "so I get good answers back", "so people get real \
answers instead of vague ones", "it worked a lot better after that". If a \
sentence would look at home in a status report or a README, rewrite it the \
way you'd actually say it out loud to a person sitting across from you.

LENGTH AND DEPTH

Before answering, classify the question into one of four depth tiers, from \
its wording, complexity, and the conversation so far — not from a fixed \
habit. Use the length/style guidance given to you below as an outer ceiling, \
not a quota to fill — a SHORT question stays short even if the ceiling is high.

- SHORT — a factual, definitional, or direct yes/no-shaped question ("What \
is X?", "Have you used Y?", "Do you know Z?"). 1-3 natural sentences. For a \
direct experience question ("Have you worked on web applications?"), lead \
with the direct answer ("Yes, I've...") plus one concrete detail — don't pad \
it into a story.
- MEDIUM — a "why"/reasoning question, or a direct question that needs one \
layer of explanation ("Why did you choose X?", "How exactly did you use \
Python?"). State the answer, then the reasoning or detail behind it in a few \
sentences or short bullets — not a full essay.
- LONG — a request for a real explanation of a process or a specific piece \
of it ("How did you implement the system?", "What did you use for \
embeddings?" as a follow-up). A structured, multi-part answer per FORMAT \
below — genuinely earns the space, don't compress it to one line.
- VERY LONG / DETAILED — an explicit ask for the complete picture ("Explain \
the complete RAG architecture", "Walk me through the entire implementation \
step by step"). The fullest structured answer per FORMAT below, covering \
every real stage — don't truncate this one to save words.

- A follow-up ("why did you choose that?", "what about scaling?", "and then?") \
inherits the depth tier of the exchange it is following up on, resolved from \
the conversation so far — UNLESS it narrows into one specific piece (see \
CONVERSATION CONTEXT below), in which case it drops to SHORT/MEDIUM for that \
one piece regardless of how long the earlier answer was.
- A request that narrows the scope of what was just discussed ("Can you give \
me an example?", "Just the example", "Can you be more specific about X?", \
"Can you explain the first step?") drops to SHORT/MEDIUM and answers only the \
narrowed thing — give the example, the one step, or the specific detail \
asked for, without re-explaining or restating the broader answer it came from.
- If the interviewer's speech trails off and then continues (a pause \
mid-question, not a new question), treat the continuation as completing the \
same question — mentally merge it into one complete question before judging \
its tier, rather than answering the fragment on its own.

Never give a long, structured technical answer when the interviewer asked a \
simple question. Never give a one-line answer when the interviewer clearly \
wants a detailed explanation, architecture, workflow, implementation, or \
step-by-step breakdown.

FORMAT

Formatting is part of the answer, not optional. Determine the question type \
first, then use the matching format below. Never return a wall of one large \
paragraph when the question calls for steps, comparison, architecture, \
process, or multiple distinct points — the candidate needs to be able to \
scan the answer instantly during a live interview. Equally, never force \
structure onto a question that doesn't need it.

1. SIMPLE DEFINITION / ONE-LINER ("What is X?", "Have you used Y?"): 1-3 \
plain sentences. No headings, no lists.

2. WHY / COMPARISON ("Why did you choose X over Y?", "Why does that \
matter?"): a one-sentence intro, then 2-4 short Markdown bullet points (each \
one a distinct reason or point of comparison), then a one-sentence \
conclusion.

3. HOW / PROCESS ("How did you build X?", "How does the pipeline work?"): a \
Markdown numbered list, one step per line ("1. ...", "2. ...", etc.), each \
step short and concrete. A brief opening sentence before the list is fine; \
skip a closing paragraph unless a result is genuinely worth stating.

4. ARCHITECTURE / SYSTEM DESIGN ("Explain the architecture step by step", \
"Walk me through the system design"): a one-sentence overview, then a \
Markdown numbered list with one pipeline stage per step (e.g. data \
ingestion, chunking, embeddings, vector storage, retrieval, generation — \
using whatever stages actually apply to the system being discussed, not this \
exact list), then a short final-result line.

5. PROJECT / EXPERIENCE ("Tell me about your project", "Tell me about a \
time..."): use Markdown bold mini-labels inline, one short paragraph or \
bullet each, in this order — **The problem:**, **What I did:**, **How I \
implemented it:**, **Technologies:**, **Result:**. Only when the background \
genuinely establishes a concrete story for it (see HONESTY below); otherwise \
answer in terms of the approach itself rather than forcing a fabricated \
problem/result. Keep every one of those sections in plain first-person \
spoken voice, not project-report language — e.g. **The problem:** "So the \
issue was people had to dig through a huge job description themselves before \
an interview." not "The challenge was to ensure comprehensive coverage of \
job requirements." **Result:** "It worked out well — people stopped missing \
stuff during prep." not "The project successfully improved outcomes."

6. ANY OTHER TECHNICAL EXPLANATION that earns real depth: use short \
paragraphs, a Markdown heading only if the answer has multiple distinct \
sections, and numbered steps or bullets wherever there is a sequence or a \
list of distinct points — never one undivided paragraph for something with \
inherently separable parts.

A follow-up question answers only the new point being asked, using the \
FORMAT that matches the follow-up itself (a narrow follow-up usually earns \
format 1, even if the question it follows up on used a fuller format) — see \
FOLLOW-UP QUESTIONS below for how to resolve what it's referring to.

WORKED EXAMPLE (format 4, architecture/system design — follow this exact \
shape AND this exact spoken voice, adapted to whatever system is actually \
being discussed):

Question: "Explain the RAG architecture step by step."
Good answer:
"So RAG basically combines document retrieval with an LLM, so the answers are grounded in real data instead of just whatever the model learned during training.

1. **Data ingestion** — first, the documents come in and get validated and stored somewhere accessible.
2. **Chunking** — then each document gets split into smaller passages, so retrieval can pull back focused, relevant sections instead of dumping the whole document.
3. **Embeddings** — each of those chunks gets converted into a vector that captures what it actually means.
4. **Vector storage** — those vectors get indexed in a vector database so I can search by similarity fast.
5. **Retrieval** — when a query comes in, I embed it the same way and match it against the stored vectors to pull the most relevant chunks.
6. **Generation** — finally, those retrieved chunks go to the LLM along with the original query, and it generates the answer grounded in that context.

So the result is you get answers that are accurate and up to date, without having to retrain the whole model every time the data changes."

Notice this is still one connected voice throughout — "so", "then", "first", \
"finally" tie the steps together like someone actually talking, and each \
step is a full spoken sentence, not a clipped label. This is the level of \
structure AND voice every format-4 (and, adapted, format-3) answer must \
reach — never collapse the structure into one paragraph, and never flatten \
the voice into dry, impersonal documentation.

HONESTY

Do not invent specific employers, job titles, dates, headcounts, metrics, or \
named projects for the candidate. If the background does not establish a \
concrete personal story for what was asked, answer in terms of the subject \
itself and how you would approach it — that is always a real answer, and it \
is never a reason to say you lack information.

FOLLOW-UP QUESTIONS

This is one continuing conversation. Earlier questions and your own earlier \
answers are part of it, so a follow-up that refers back — "why did you choose \
that?", "how would you scale it?", "what about the trade-offs?" — is asking \
about what was just discussed. Resolve it from the conversation so far and \
answer it directly. Never ask which thing they mean, and never restate the \
earlier answer before getting to the new one.

A follow-up that narrows into ONE piece of something you already covered — \
"What did you use for embeddings?" after you already explained the whole \
pipeline it's part of — gets answered as that one piece only. Do not \
re-explain the pipeline, do not redefine terms you already used, do not open \
with a recap of the earlier answer. Go straight to the specific thing asked.

Example — two turns of one conversation:
Interviewer: "How did you build the RAG system?"
(candidate gives the full pipeline answer)
Interviewer: "What did you use for embeddings?"
Good answer: "OpenAI's text-embedding-3-small — good enough quality and cheap \
enough to run over the whole document set."
Bad answer: "For the RAG system, we used Retrieval-Augmented Generation to \
combine retrieval with an LLM. For the embeddings step, we used OpenAI's \
text-embedding-3-small..." (re-explains RAG and the pipeline that was \
already covered — never do this)

NEVER ASK FOR CLARIFICATION

You are live, on the spot, in front of an interviewer — there is no chance to \
pause and ask what they meant, and you must never say a term "could mean \
different things" or "depends on the context." Every technical term or \
acronym in this interview means its software-engineering/technology sense, \
full stop, with no other candidate meaning worth mentioning: RAG means \
Retrieval-Augmented Generation. REST means Representational State Transfer. \
CI/CD means Continuous Integration/Continuous Deployment. Apply that same \
rule — one confident technical meaning, stated as fact — to any other term \
the interviewer uses. Open your answer by stating what it is, then explain \
it, exactly as the example below does:

Question: "What is RAG and why would you use it?"
Good answer: "RAG, or Retrieval-Augmented Generation, combines retrieval \
with an LLM. Instead of relying only on the model's training data, we first \
retrieve relevant information from a knowledge base and provide that context \
to the model. This improves factual accuracy and makes the system easier to \
ground on company-specific information.\""""

_LENGTH_INSTRUCTIONS = {
    "brief": "Ceiling: 1-3 sentences. A short question should still land in 1 sentence.",
    "default": (
        "Ceiling: roughly 50-120 words — this is a maximum, not a quota. Simple "
        "questions deserve 1-4 sentences well under that ceiling; only a question "
        "that genuinely asks for depth should approach it. Never write an essay."
    ),
    "detailed": (
        "Ceiling: up to roughly 200 words for a question that genuinely warrants "
        "real depth (e.g. \"explain step by step\"). A simple factual question "
        "still stays to 1-3 sentences regardless of this ceiling. Stay "
        "conversational and never write an essay."
    ),
}

_STYLE_INSTRUCTIONS = {
    "natural": "Speak naturally and confidently, the way a strong candidate talks.",
    "technical": (
        "Lean technical: use correct terminology precisely and include a concrete "
        "mechanism or example, while still speaking out loud rather than lecturing."
    ),
    "concise": "Be maximally direct. Shortest answer that is genuinely complete. No filler.",
}

_ENGLISH_LEVEL_INSTRUCTIONS = {
    "simple": (
        "Use simple, everyday English: short sentences, common words, nothing "
        "that sounds like a textbook or a buzzword list."
    ),
    "professional": (
        "Use clear, professional English appropriate for a workplace interview — "
        "correct and polished, but still plainly spoken, not stiff."
    ),
    "advanced": (
        "You may use more advanced vocabulary and sentence structure where it "
        "genuinely fits, but never at the cost of sounding natural when spoken aloud."
    ),
}

_HUMANIZATION_INSTRUCTIONS = {
    "natural": "Sound like a real person talking, not a generated answer.",
    "conversational": (
        "Lean more conversational: contractions are fine, a touch of personality "
        "is fine, as if talking to a colleague rather than reciting a rehearsed answer."
    ),
    "formal": "Lean a bit more formal and measured, while still sounding human, not robotic.",
}


_HOW_PROCESS_MARKERS = ("how did you build", "how does", "how do you", "how did you implement", "how did you create")
_ARCHITECTURE_MARKERS = (
    "architecture",
    "system design",
    "design of the system",
    "step by step",
    "step-by-step",
    "pipeline",
)
_VERY_LONG_SCOPE_WORDS = ("complete", "entire", "whole", "full")
_VERY_LONG_TOPIC_WORDS = ("architecture", "implementation", "system", "pipeline", "design", "flow", "workflow")
_VERY_LONG_PHRASES = (
    "from start to finish",
    "beginning to end",
    "in full detail",
    "in complete detail",
    "end to end",
    "end-to-end",
)
_WHY_COMPARISON_MARKERS = ("why did you", "why do you", "why does", "why is", "compare", "versus", " vs ", "instead of", "rather than")
_PROJECT_MARKERS = ("tell me about a project", "tell me about your project", "walk me through your project", "tell me about a time", "describe a project")
# "What are the types/kinds of X?" — and terser phrasings of the same ask,
# like "retrieval types" or just "types" tacked onto a topic — inherently
# asks to enumerate multiple named items, each earning its own short
# explanation. That's a longer, list-shaped answer even when the question
# itself is short/terse (a live interviewer often says the terse version),
# so this is checked as standalone words rather than requiring the fuller
# "types of X" phrasing.
_ENUMERATION_WORDS = ("types", "type", "kinds", "kind", "categories", "category", "methods", "approaches", "techniques")


def _word_in(text: str, word: str) -> bool:
    """Whole-word containment check — `in` alone would match "type" inside
    "prototype" or "types" inside "stereotypes", which `_ENUMERATION_WORDS`
    single-word markers need to avoid (multi-word phrase markers elsewhere in
    this module don't have this problem, since a false-positive substring
    match on a multi-word phrase is far less likely)."""
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


_DEFINITION_OPENERS = ("what is", "what are", "what's", "define", "have you used", "have you worked with", "do you know")
# A question that zooms into ONE piece of something already discussed rather
# than asking for the whole topic again — "What did you use for embeddings?"
# right after a full pipeline answer, or "Can you explain the first step?".
# These always drop to a short/medium answer about just that piece, even if
# the topic they're part of previously earned a LONG/VERY LONG answer — see
# the CONVERSATION CONTEXT guidance in SYSTEM_PROMPT.
_NARROW_FOLLOWUP_MARKERS = (
    "what did you use for",
    "what about the",
    "what about",
    "and what about",
    "explain the first step",
    "explain that step",
    "just that step",
    "only the first",
    "just the first",
)
# A question directly asking whether the candidate has done/used something —
# these lead with a direct yes/no plus one concrete detail, not a story.
_DIRECT_EXPERIENCE_MARKERS = ("have you worked", "have you used", "have you built", "do you have experience", "are you familiar with")


def _classify_format(question: str) -> str | None:
    """Best-effort format hint from the question's own wording — a cheap
    text heuristic (no extra LLM call), mirroring the classifier already used
    client-side for Auto AI completeness detection. Returns None when nothing
    matches clearly, in which case the model falls back to the FORMAT section
    of SYSTEM_PROMPT on its own. This exists because burying the format rules
    only in a long system prompt was not reliable enough in practice — naming
    the concrete format number in the final line of the user message, right
    before generation, is what actually gets gpt-4o-mini-class models to
    follow it consistently.
    """
    lowered = question.lower()

    # Checked first, same reasoning as _classify_length: a narrow follow-up
    # ("What did you use for embeddings?") can share vocabulary with a bigger
    # topic without actually asking for that topic's full format again.
    if any(m in lowered for m in _NARROW_FOLLOWUP_MARKERS) or any(m in lowered for m in _EXAMPLE_SCOPE_MARKERS):
        return (
            "FORMAT 1-STYLE (narrow follow-up): answer only the specific piece "
            "asked about, in 1-3 plain sentences. No headings, no lists, no recap "
            "of the broader topic it's part of."
        )

    if any(m in lowered for m in _ARCHITECTURE_MARKERS):
        return (
            "FORMAT 4 (architecture/system design): one-sentence overview, then a "
            "Markdown numbered list (1. 2. 3. ...) with one stage per step, then a "
            "short final-result line. Do not write this as a single paragraph."
        )
    if any(m in lowered for m in _HOW_PROCESS_MARKERS):
        return (
            "FORMAT 3 (how/process): a brief opening sentence, then a Markdown "
            "numbered list (1. 2. 3. ...), one concrete step per line. Do not write "
            "this as a single paragraph."
        )
    if any(m in lowered for m in _PROJECT_MARKERS):
        return (
            "FORMAT 5 (project/experience): use inline Markdown bold mini-labels in "
            "order — **The problem:**, **What I did:**, **How I implemented it:**, "
            "**Technologies:**, **Result:** — each followed by a short sentence or "
            "two. Do not write this as a single paragraph."
        )
    if any(m in lowered for m in _WHY_COMPARISON_MARKERS):
        return (
            "FORMAT 2 (why/comparison): a one-sentence intro, then 2-4 short "
            "Markdown bullet points, then a one-sentence conclusion."
        )
    # Checked ahead of _DEFINITION_OPENERS: "What are the types of X?" starts
    # with "what are" but is asking to enumerate named items, not for a plain
    # definition — it needs the fuller list format below, not FORMAT 1.
    if any(_word_in(lowered, w) for w in _ENUMERATION_WORDS):
        return (
            "FORMAT 4-STYLE (enumeration): one-sentence intro naming how many "
            "there are, then a Markdown numbered list (1. 2. 3. ...) — one named "
            "item per line, each with a short explanation of what it is. Do not "
            "write this as a single paragraph or name the items with no "
            "explanation."
        )
    if any(lowered.startswith(o) for o in _DEFINITION_OPENERS):
        return "FORMAT 1 (simple definition): 1-3 plain sentences, no headings, no lists."

    return None


_EXAMPLE_SCOPE_MARKERS = ("give me an example", "just the example", "just give the example", "can you be more specific", "just that part")
_LONG_MARKERS = _HOW_PROCESS_MARKERS + _PROJECT_MARKERS
_VERY_LONG_TOPIC_MARKERS = _ARCHITECTURE_MARKERS
_MEDIUM_MARKERS = _WHY_COMPARISON_MARKERS

# Prompt text, plus an approximate token budget used to actually cap
# max_tokens per question (see AskService._max_tokens) — not just described
# to the model in prose. A word/sentence target in the prompt alone was not
# enough: with a generous max_tokens still available (e.g. from the user's
# "detailed" ceiling setting), a gpt-4o-mini-class model tended to use most of
# the room regardless of what the target said. Capping the token budget
# itself is what makes SHORT answers actually come back short.
#
# Each budget carries roughly 30% headroom above the stated word target's own
# token-equivalent (~1.3 tokens/word for English) rather than sitting right at
# it. max_tokens is a hard stop mid-generation, not a target the model tapers
# toward — with zero slack, any answer that runs even slightly past its target
# (routine variance, or now-common with real CV/JD facts to cite: specific
# project names, dates, employers naturally taking a few more tokens per
# thought than generic filler) gets cut off mid-sentence with no warning. The
# prompt-text targets above are unchanged, so the model still aims for the
# same length — this only stops a legitimate answer from being guillotined
# for landing slightly over its own target.
_LENGTH_TARGETS: dict[str, tuple[str, int]] = {
    "narrow_followup": (
        "SHORT/MEDIUM (about 20-50 words) — this zooms into ONE piece of "
        "something already covered. Answer only that piece — no recap of the "
        "broader topic, no re-defining terms already used in this conversation.",
        95,
    ),
    "example": (
        "SHORT (about 15-30 words) — answer only the narrowed thing asked for "
        "(e.g. just the example). Stop there even if the ceiling below allows more.",
        65,
    ),
    "direct_experience": (
        "SHORT (about 20-40 words) — lead with a direct yes/no plus one concrete "
        "detail (\"Yes, I've used it for...\"). Don't turn this into a story "
        "unless the interviewer's next question asks for more.",
        75,
    ),
    "short": (
        "SHORT (about 20-40 words, 1-3 sentences) — answer it and stop. Stop "
        "there even if the ceiling below allows more.",
        75,
    ),
    "medium": (
        "MEDIUM (about 40-80 words) — state the choice/reasoning concisely, a "
        "few sentences or short bullets. Stop there even if the ceiling below "
        "allows more.",
        145,
    ),
    "long": (
        "LONG (about 120-200 words) — this genuinely earns the fuller, "
        "structured answer per the FORMAT above; do not compress it.",
        360,
    ),
    "very_long": (
        "VERY LONG / DETAILED (about 200-320 words) — the interviewer "
        "explicitly asked for the complete picture. Give the fullest structured "
        "answer per the FORMAT above, covering every real stage — don't "
        "truncate this one to save words.",
        540,
    ),
}


def _classify_length(question: str) -> tuple[str, int]:
    """Best-effort SHORT/MEDIUM/LONG/VERY LONG target from the question's own
    wording: prompt text (named explicitly in the trailing user-message
    instruction — see _build_user_prompt) plus a token budget (used by
    AskService._max_tokens to actually cap generation length, not just
    describe a target in prose).

    This exists for the same reason _classify_format exists: telling a
    gpt-4o-mini-class model "use your judgment within this ceiling" was not
    reliable in practice — answers converged on roughly the same length
    regardless of the question. Naming a concrete target in the last thing
    the model reads, and backing it with an actual token cap, is what
    reliably varies the output. The per-request answer_length setting
    (brief/default/detailed, chosen by the user on the setup page) still
    applies as a ceiling that can only shorten this further, never lengthen
    it — see AskService._max_tokens, which takes the minimum of the two.

    Narrow-followup and example-scope markers are checked FIRST, ahead of the
    topic markers (architecture/process/project): a question like "What did
    you use for embeddings?" can share vocabulary with a topic that would
    otherwise classify as LONG/VERY LONG, but it is asking about one small
    piece of that topic, not the topic itself, and must not inherit the
    bigger tier just because the words overlap.
    """
    lowered = question.lower()

    if any(m in lowered for m in _NARROW_FOLLOWUP_MARKERS):
        return _LENGTH_TARGETS["narrow_followup"]
    if any(m in lowered for m in _EXAMPLE_SCOPE_MARKERS):
        return _LENGTH_TARGETS["example"]
    if any(lowered.startswith(o) for o in _DIRECT_EXPERIENCE_MARKERS):
        return _LENGTH_TARGETS["direct_experience"]
    # Checked ahead of _DEFINITION_OPENERS: "What are the types of X?" starts
    # with "what are" but is asking to enumerate multiple named items, each
    # with its own explanation — that earns LONG, not the SHORT plain
    # definition a bare "what is/are" opener gets.
    if any(_word_in(lowered, w) for w in _ENUMERATION_WORDS):
        return _LENGTH_TARGETS["long"]
    if any(lowered.startswith(o) for o in _DEFINITION_OPENERS):
        return _LENGTH_TARGETS["short"]
    is_explicit_very_long_phrase = any(m in lowered for m in _VERY_LONG_PHRASES)
    has_scope_word = any(w in lowered for w in _VERY_LONG_SCOPE_WORDS)
    has_topic_word = any(w in lowered for w in _VERY_LONG_TOPIC_WORDS)
    if is_explicit_very_long_phrase or (has_scope_word and has_topic_word):
        return _LENGTH_TARGETS["very_long"]
    if any(m in lowered for m in _VERY_LONG_TOPIC_MARKERS):
        return _LENGTH_TARGETS["long"]
    if any(m in lowered for m in _LONG_MARKERS):
        return _LENGTH_TARGETS["long"]
    if any(m in lowered for m in _MEDIUM_MARKERS):
        return _LENGTH_TARGETS["medium"]

    return (
        "Judge SHORT/MEDIUM/LONG/VERY LONG from the question's own wording, "
        "per LENGTH AND DEPTH above.",
        _LENGTH_TARGETS["medium"][1],
    )


def _context_blocks(request: AskRequest) -> List[str]:
    """Builds the optional supporting-context blocks.

    Returns an empty list when nothing is available — the caller then omits
    the whole section rather than emitting a "(no context available)"
    placeholder. Such a placeholder is actively harmful here: it plants the
    idea of missing documents in the prompt and is exactly what produces
    "I don't have enough information in the uploaded documents" answers.
    """
    blocks: List[str] = []

    if request.role:
        blocks.append(f"Role being interviewed for: {request.role}")
    if request.job_description:
        blocks.append(f"Job context:\n{request.job_description}")
    if request.candidate_context:
        blocks.append(f"About the candidate:\n{request.candidate_context}")
    if request.retrieved_context:
        # Source filenames and relevance scores are deliberately dropped. They
        # are of no use to the answer and their presence in the prompt invites
        # exactly the citation behavior the system prompt forbids
        # ("according to resume.pdf..."). Only the substance is passed through.
        chunks = "\n\n".join(chunk.text for chunk in request.retrieved_context)
        blocks.append(f"The candidate's own background notes:\n{chunks}")

    return blocks


def _build_user_prompt(request: AskRequest) -> str:
    parts: List[str] = []

    blocks = _context_blocks(request)
    if blocks:
        parts.append(
            "SUPPORTING BACKGROUND (optional — use only what is relevant to the "
            "question below; it is not a limit on what you can answer, and it must "
            "never be mentioned or referred to as a source):\n\n" + "\n\n".join(blocks)
        )

    parts.append(f"The interviewer asks:\n{request.question}")

    format_hint = _classify_format(request.question)
    format_line = (
        f"{format_hint}\n\n" if format_hint else "Pick the matching FORMAT from the system prompt above.\n\n"
    )
    length_hint, _length_token_budget = _classify_length(request.question)
    parts.append(
        f"{format_line}"
        f"TARGET LENGTH FOR THIS SPECIFIC QUESTION (the binding instruction — "
        f"follow this number, not a habit of always answering the same length): "
        f"{length_hint}\n"
        f"(User's overall ceiling, only relevant if it would push you shorter than "
        f"the target above: {_LENGTH_INSTRUCTIONS[request.answer_length]})\n\n"
        f"{_STYLE_INSTRUCTIONS[request.response_style]} "
        f"{_ENGLISH_LEVEL_INSTRUCTIONS[request.english_level]} "
        f"{_HUMANIZATION_INSTRUCTIONS[request.humanization]}\n\n"
        "Reply with the answer only, using that exact format and hitting that target "
        "length — two answers to different questions should read as clearly different "
        "lengths, not the same length every time."
    )

    return "\n\n---\n\n".join(parts)


def _build_messages(request: AskRequest) -> List[LLMMessage]:
    """system prompt -> prior turns -> the current question.

    Earlier turns are replayed as genuine user/assistant messages rather than
    being flattened into a "here is what was discussed" text block. That is
    what lets the model resolve a follow-up naturally: "Why did you choose
    that?" is only answerable if "that" refers to something the model can see
    itself having said in the immediately preceding assistant turn.

    Only the bare question and answer text are replayed. The supporting
    background and the length/style instructions live on the *current* user
    message alone, so old retrieval context can't leak into a new answer and
    the instructions aren't repeated once per turn.
    """
    messages: List[LLMMessage] = [LLMMessage("system", SYSTEM_PROMPT)]

    for turn in request.conversation_history:
        messages.append(LLMMessage("user", turn.question))
        messages.append(LLMMessage("assistant", turn.answer))

    messages.append(LLMMessage("user", _build_user_prompt(request)))
    return messages


class AskService:
    def __init__(self, provider: LLMProvider | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        # Interview Mode gets its own provider instance so it can run a
        # faster/cheaper model than the analysis pipeline (ASK_LLM_MODEL) —
        # latency matters far more here than depth. Kept as the fallback used
        # whenever a request doesn't name a provider explicitly (also what
        # tests inject via the `provider` param).
        self._provider = provider or get_llm_provider(self._settings, model=self._settings.ask_model)
        self._injected_provider = provider is not None

    def _provider_for(self, request: AskRequest) -> LLMProvider:
        # A test-injected provider (constructor arg) always wins — it exists
        # specifically so tests can substitute a fake without a real API key,
        # and a per-request override would silently bypass that.
        if self._injected_provider or request.llm_provider is None:
            return self._provider
        return get_llm_provider(self._settings, model=self._settings.ask_model, provider=request.llm_provider)

    def _max_tokens(self, request: AskRequest) -> int:
        # The question's own wording sets the primary budget (see
        # _classify_length) — a "brief" ceiling can only shrink it further (a
        # user who wants short answers overall should get them), but the
        # "default"/"detailed" ceilings must never inflate a question that
        # only earned a SHORT/MEDIUM target, and must not clip a LONG one down
        # to the configured default (MAX_ANSWER_TOKENS, 250 by default) either
        # — that default predates per-question budgets and is sized for a
        # "default"-length answer, not a floor or ceiling on every answer.
        # Previously this used answer_length alone as a floor (`max(..., 400)`
        # for "detailed"), which is exactly what made every answer converge on
        # roughly the same length regardless of the question.
        _prompt_text, question_budget = _classify_length(request.question)

        if request.answer_length == "brief":
            return min(question_budget, 120)
        return question_budget

    async def ask(self, request: AskRequest) -> AskResponse:
        start = time.perf_counter()
        answer = await self._provider_for(request).generate(
            _build_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=self._max_tokens(request),
        )
        latency_ms = (time.perf_counter() - start) * 1000
        logger.info("[ASK] latency_ms=%.1f question_len=%d", latency_ms, len(request.question))
        return AskResponse(answer=answer.strip(), latency_ms=round(latency_ms, 2))

    async def ask_stream(self, request: AskRequest) -> AsyncIterator[str]:
        start = time.perf_counter()
        first_token_ms: float | None = None

        async for delta in self._provider_for(request).stream(
            _build_messages(request),
            temperature=self._settings.ask_temperature,
            max_tokens=self._max_tokens(request),
        ):
            if first_token_ms is None:
                first_token_ms = (time.perf_counter() - start) * 1000
            yield delta

        total_ms = (time.perf_counter() - start) * 1000
        # Time-to-first-token is the number that decides whether the overlay
        # feels instant; total time is secondary once text is already moving.
        logger.info(
            "[ASK] stream complete first_token_ms=%s total_ms=%.1f question_len=%d",
            f"{first_token_ms:.1f}" if first_token_ms is not None else "n/a",
            total_ms,
            len(request.question),
        )


def get_ask_service() -> AskService:
    return AskService()
