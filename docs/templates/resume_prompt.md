# Resume prompt template

Every handoff ends with a `## Resume prompt` section containing a fenced copy of this template with every
`{{field}}` filled in. Lines starting with `>` are guidance: delete them in the copy. Keep the copy
self-contained: a fresh session reads nothing but it and the files it names.

````
Resume the biomegen -> worldgen-style redesign at PHASE {{phase_number}} ({{phase_name}}),
SUBPHASE {{subphase_or_none}}, starting at TASK {{task_number_and_name}}.
Work in the repo root: the directory this session was launched in. Do not assume a path.

Read, in order:
> Newest-first handoff, then the plan sections for this phase, then the rules. Name sections, not whole files.
1. {{handoff_file_and_section}}
2. {{plan_sections_to_read}}
3. {{other_files}}

Rules (settled; do not re-litigate):
> Copy the current rules from the root CLAUDE.md and any user decisions made since. Add new ones; drop none
> silently.
- {{rule}}

Verify, report any mismatch, and stop if one is found:
> One line per check: the command, then the exact expected output (commit hash, status lines, test counts).
a. {{command}} -> {{expected_output}}

Then, in this order:
> The first actions of the session, each small enough to finish and report.
1. {{first_action}}

Stop conditions: {{stop_conditions}}
> Always include: any verification mismatch; a test or fingerprint difference you cannot explain; anything
> that needs a decision from the user.
Report: {{what_to_report}}
> Always include: what changed, test and fingerprint results, open questions, risks.
At the end of the phase, write the handoff (a new top section in docs/handoffs/landed-work.md) ending with a
`## Resume prompt` built from docs/templates/resume_prompt.md for the next piece of work.
````

## Field reference

| Field | Fill with |
|---|---|
| `phase_number`, `phase_name` | From `docs/redesign_plan.md` section 7 |
| `subphase_or_none` | Subphase label, or `none` |
| `task_number_and_name` | The first unfinished task in the phase's todo list |
| `handoff_file_and_section` | e.g. `docs/handoffs/landed-work.md, top section only` |
| `plan_sections_to_read` | Plan sections that describe this phase, plus any it depends on |
| `command` / `expected_output` | Exact commands (`scripts/*.sh`, `uv run ...`) and their expected output |
| `stop_conditions` | Conditions that need the user, beyond the three standing ones above |
