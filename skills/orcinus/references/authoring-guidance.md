# Skill-authoring guidance

Guidance for writing or revising a skill so that it actually changes
what an agent does. The patterns here are adapted in ORCINUS's own
words from obra/superpowers (`skills/writing-skills/SKILL.md`,
"Match the Form to the Failure" and "Micro-Test Wording Before Full
Scenarios", MIT) and from rebelytics/one-skill-to-rule-them-all
(`references/signals.md`, "Second violation — why a barrier, not a
rewording", CC-BY-4.0) — pattern-only; no upstream text is copied.

## Match the form to the failure

Before writing guidance, name the failure you actually see in the
baseline behaviour. The shape of guidance that fixes one kind of
failure makes another kind worse, so pick the form from the failure,
not from habit.

1. **Rule-violations under pressure** — the agent knows the rule and
   breaks it anyway when rushed, pressed, or pulled by a competing
   demand. Use a prohibition plus a rationalisation table (the excuses
   the agent will reach for, each answered in advance) plus red flags
   (the observable signs the rule is being dodged). Soft wording
   ("prefer…", "consider…") does not hold under pressure.
2. **Wrong-shaped output** — the agent complies, but the output comes
   out the wrong shape: the verdict buried, the spec restated, the
   prompt bloated. Use a positive recipe or contract: spell out the
   output's parts and their order. Never a prohibition list: under a
   competing incentive an agent argues with "don't X", and the
   unwanted content shows up more, not less.
3. **Omitted elements** — the agent already produces the thing, but
   leaves a required element out of it. Use a REQUIRED template slot
   in the template it fills in. Prose reminders sitting next to the
   template get skipped.
4. **Conditional behaviour** — what to do depends on a condition. Key
   the conditional to an observable predicate: the branch turns on
   something you can see ("if the deadline passed, escalate it").
   Never "don't X unless…": a nuance clause reopens the negotiation,
   and an exemption clause does not scope — it suppresses the
   exempted part too. Handle a genuine exception with its own branch,
   switched on something you can observe.

## Micro-test the wording before full scenarios

Full pressure scenarios are the last gate, but each iteration
through them is slow and expensive. Test the wording itself first,
cheaply:

1. **One sample per call, each from a fresh context** — a direct
   API call, or a one-shot subagent where no API is available. Put
   the guidance in its real home as the system prompt — the whole
   skill or prompt template, not the guidance on its own — and give
   a task that tempts the failure as the user message.
2. **Always run a no-guidance control.** If the failure never
   appears in the control, the guidance has nothing to fix — stop
   before writing it.
3. **5+ reps per variant.** One sample by itself proves nothing.
4. **Read every flagged match by hand.** Automated scoring is fine
   as a first pass, but quoted counter-examples and template echoes
   read as hits, so counts by themselves overstate failure and
   success alike.
5. **Variance tells you the wording is working.** When the guidance
   lands, the reps settle on one shape. If five reps give five
   different shapes, the wording isn't binding: the form needs
   tightening, not more words.

Micro-tests check wording only. They do not stand in for full
pressure scenarios on discipline skills.

## Second violation — build a barrier, not a better sentence

When a rule fails for the second time, stop rewriting it. A rule that
has failed twice must be fixed with a structural barrier — a hook, a
lint rule, or a default — never a clearer sentence.

Why text loses: a rule sitting in context is re-read and
re-interpreted on every run, and it competes with everything else
pulling at the agent in that moment. A barrier at the tool boundary
is not in the contest — it blocks the call, rejects the artefact, or
takes the wrong action off the table. Emphasis does not change that
asymmetry: a bolder rule is still a rule, and rewriting it again
looks like care while the measured behaviour stays the same.

What counts as a barrier: a permission gate or hook that blocks the
call; a gate or lint check that rejects the artefact; defaults and
paths arranged so the wrong action cannot be taken; a script that
does the step itself, leaving no other way to do it. What does not
count: a louder warning, the same rule pasted somewhere more
visible, an item added to a checklist, or a promise to take more
care.

A barrier is real once it is switched on and proven, not once it is
described: prove it on two real cases — one call it must refuse and
one call it must allow — both taken from the real tool record.
