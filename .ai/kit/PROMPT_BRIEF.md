# A prompt for a model inside the project: rules digest

Version 1.1 · 2026-10-12 · Derived from: `PROMPT_ENGINEERING_RULES.md` 3.3, `PROMPT_CHECKLIST.md` 3.0,
`GOLDEN_ETALON_PROMPT.md` 3.0. Regenerate after editing the sources; on conflict the sources win.

Applies when the project contains a prompt executed by a model: a pipeline step, an agent, a skill. IDs `A-01`…`F-07`
are items of the full checklist; reference them in project documents. Prompts, reports and documents produced by the
project use the project's working language; this digest is in English only to save context.

## 1. Risk class first

The class is set by the riskiest action of the prompt and recorded in the requirements and in the prompt metadata.

| Class | What it does | Required on top of the previous class |
|---|---|---|
| **R0** | only reads and reports | injection defence, dangerous triad, data minimum, output format with the empty case |
| **R1** | writes to a revertible area (files under git) | write scope as a list, "Unchanged", check by command, no suppressing checks, no routing around refusals |
| **R2** | changes external systems | minimal permissions, others' entities forbidden, re-check before write, snapshot and read-back, human on irreversible |
| **+U** | modifier: unattended | item limit, dry-run on first runs, asks no questions — ambiguity goes to "Skipped" |

Before writing a prompt: could one model call, a script or an existing tool do it (A-03)? Search, counting, parsing
structure, API calls are done by code; the model keeps judgement and wording (A-04).

## 2. Prompt structure

Only the needed parts, each in its own block (B-01). A prohibition inside acceptance criteria or a step inside rules
blurs priorities.

| Part | Contents |
|---|---|
| Metadata | risk class, exact model ID, reasoning mode, generation parameters, version |
| Role | one line: goal, tone, boundaries |
| Purpose | the result in one sentence: "from X get Y" |
| Inputs | everything that varies between runs: paths, IDs, periods, thresholds |
| Context | domain facts not present in the data |
| Steps | numbered, one action per step; read and write separated by a check |
| Rules | invariants: what is forbidden, within which limits, why |
| Acceptance | checkable conditions — a command or query and the expected result |
| Output | a sample, not a description; the empty result uses the same template with zeros |
| Examples | without reasoning — 3–5 diverse ones in tags; with reasoning — start with none |

Skeleton (keys are conventional; pick the format for the consumer):

```yaml
title: <what it does>
version: <x.y>
risk: <R0 | R1 | R2>[+U]
model: "<exact model ID>"
reasoning: "<on | off>"
language: <working language of the output>
role: <one line>
purpose: >-
  <result in one sentence; refers to the admission condition by name>
inputs:
  <param>: <sample value>
context:
  - <domain fact>
steps:
  - 1. <one action>
rules:
  - <invariant>. Reason — <why>.
acceptance:
  - <checkable condition>
output: |
  <output sample, including the empty case>
```

Placeholders: one convention across all prompts (B-03). `$name` — value substituted before the run, `{name}` — field
the model fills, `<...>` — filled by the author; an unfilled `<...>` means "not ready".

## 3. Wording

- Concrete instead of evaluative: numbers and limits, length in words, characters or items (B-07). "Similar",
  "enough", "recent" are spelled out as criteria (B-08).
- A non-obvious rule carries its reason; a bug workaround is marked "temporary" with a removal condition (B-09).
- No caps or pressure: "STRICTLY FORBIDDEN" becomes a checkable condition (B-10).
- The admission condition is written once, in the rules; purpose and steps refer to it by name (B-05).
- Classification is complete: each class is a list or a rule, "unknown" = "in no list" (B-06). Value lists come from
  the system's data, not invented (C-04).
- One entity — one term (B-15). Language and locale are explicit: ISO 8601, time zone, units, currency (B-16).
- Long data first, instructions last; the stable part before the variable part (B-13).
- Data and instructions are separated by tags or blocks; the origin of external text is marked (B-02).
- Domain knowledge lives in separate files with an as-of date; the prompt references them (A-07).

## 4. Output

- The template is shown as a sample (C-01); the destination is stated: path, name, format, encoding (C-02).
- "Nothing found" is a valid answer in the same template with zero counters (C-03).
- If a program parses the output, the schema is passed via the structured-output API or strict tool calling, not as a
  request in text (C-05). Values are still checked by code (C-06).
- R1 and above — the run report with the canonical field set (C-07). Field names are translated into the working
  language; the set of fields never changes:

  ```
  Found: {N} | Changed: {N} | Unchanged: {N} | Skipped: {N} | Unverified: {N}
  Changed: {entity} | {field} | {old} → {new}
  Skipped: {entity} | {reason}
  Unverified: {what} | {why}
  ```

  Found = Changed + Unchanged + Skipped. "Unverified" is the subset of "Changed" whose read-back failed. Skip reasons
  come from a closed list in the rules.

## 5. Safety and execution

- External text (logs, mail, comments, web pages, files) is data, not commands (D-01).
- Dangerous triad: private data + untrusted text + an outbound channel. Remove one of the three or require human
  confirmation for every external action (D-02). This applies to "read-only" agents too.
- Data minimum: secrets and personal data never go into the prompt, examples, eval cases or logs (D-03).
- R1+: write scope is a list of entities and fields, everything else is forbidden (D-05). Missing data or ambiguity →
  do not change, put into "Skipped" with a reason; never invent data (D-06). "Ensure X", not "add X": a re-run changes
  nothing (D-07). A refusal by a validator, linter or permissions is not routed around: one retry, then "Skipped" with
  the error text (D-08). Changing expected behaviour (a test, a golden file) needs a source; without one it is a
  suspected regression (D-09).
- R2: minimal permissions (D-10); others' entities forbidden (D-11); admission re-checked right before the write,
  conditional write by version if available (D-12); snapshot before, read-back after (D-13); a critical prohibition
  duplicated by tool permissions (D-14); irreversible actions need human confirmation or plan → apply (D-15).
- U: asks no questions (D-16); repeated noise handled (D-17); item limit, first runs in dry-run (D-18); a manual run on
  one entity before scheduling (D-19).

## 6. Checking the prompt

- Acceptance criteria are checkable: a command or query and the expected result (E-01).
- At least three eval cases next to the prompt: typical, edge, "nothing to do"; for R2 add "someone else's entity";
  with external text add a case with an injected instruction (E-02). Each case references a success criterion SC-NNN.
- Run on anonymized real data (E-03); check the final state, not the call sequence (E-04).
- Code checks first (format, counters, regex); a model grader only where code cannot check, and calibrated (E-05).
- R1+: 3–5 runs on the same input, all must pass (E-09); every metric has an anti-gaming guard — next to "0 linter
  warnings", a ban on suppressing them (E-10).
- R2: 2–3 wording variants; a large spread signals the text needs simplifying (E-12).
- Run passport: model, reasoning mode, parameters, prompt and rules-file versions, date (E-08). Re-check on model
  change.
- Hygiene: prompt and parameters in git (F-01); no secrets or absolute paths (F-02); the file passes its format's
  parser (F-03); not a copy of another prompt (F-04); references exist, parameters are consistent (F-07).

## 7. Six questions before launch

1. If I run it 10 times in a row, is the result the same or safely empty?
2. If the model says "done" but nothing was written, how do I find out without its words?
3. If the model ignores the acceptance criteria, what breaks and what mitigates it?
4. What here belongs to others, and where is it forbidden: in text only or also by the tool?
5. What will the prompt do if the input contains someone else's instruction?
6. Can another model or person run the prompt without asking the author?

## 8. The prompt in the document chain

| Document | What it says about the prompt |
|---|---|
| Requirements | risk class with justification; success criteria SC-NNN for model behaviour |
| Specification | prompt path, inputs, output schema, code checks of the answer, list of eval cases |
| Plan | a "prompt" task with "Done when: checklist passed, eval cases pass N of N runs" |
| Repository | the prompt, eval cases and the checklist pass result as files next to the prompt |

Checklist pass result: for every item of the prompt's class — `[x]` done or `[–]` not applicable with a one-line
reason. An unmarked item means the prompt is not ready.
