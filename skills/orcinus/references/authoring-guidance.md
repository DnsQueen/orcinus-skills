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
   prompt bloated. Use a positive recipe or contract: state what the
   output IS — its parts, in order. Never a prohibition list: under a
   competing incentive an agent argues with "don't X", and the
   unwanted content shows up more, not less. With a recipe the check
   is mechanical: the output either matches the stated shape or it
   does not.
3. **Omitted elements** — the agent already produces the thing, but
   leaves a required element out of it. Use a REQUIRED template slot
   in the template it fills in. Prose reminders sitting next to the
   template get skipped.
4. **Conditional behaviour** — what to do depends on a condition. Use
   a conditional keyed to an observable predicate ("if the brief
   exists, reference it"). Never "don't X unless…": a nuance clause
   reopens the negotiation, and an exemption clause does not scope —
   it suppresses the exempted part too. A real exception gets its own
   conditional, on something observable.

## Micro-test the wording before full scenarios

Full pressure scenarios are the final gate, but they are slow and
expensive per iteration. Test the wording itself first, cheaply:

1. **One fresh-context sample per call** — a raw API call, or a
   single-shot subagent if there is no API access. The system prompt
   is the realistic context the guidance will live in (the full skill
   or prompt template, not the guidance on its own); the user message
   is a task that tempts the failure.
2. **Always include a no-guidance control.** If the control does not
   show the failure, there is nothing to fix — stop, do not write the
   guidance.
3. **5+ reps per variant.** A single sample lies.
4. **Read every flagged match by hand.** Score programmatically if
   you like, but template echoes and quoted counter-examples look
   like hits; automated counts alone overstate both failure and
   success.
5. **Variance is a signal.** When guidance lands, the reps converge
   on one shape. If five reps give five different shapes, the
   wording isn't binding — tighten the form before adding more words.

Micro-tests check wording only. They do not replace full pressure
scenarios for discipline skills.

## Second violation — build a barrier, not a better sentence

When a rule fails for the second time, stop rewriting it. A rule that
has failed twice must be fixed with a structural barrier — a hook, a
lint rule, or a default — never a clearer sentence.

Why text loses: a rule sitting in context is re-read and
re-interpreted on every run, and it competes with everything else
pulling at the agent in that moment. A barrier at the tool boundary
does not compete — it refuses the call, fails the artefact, or makes
the wrong action unavailable. Emphasis does not change that
asymmetry: a bolder rule is still a rule, and rewriting it again
looks like care while the measured behaviour stays the same.

What counts as a barrier: a hook or permission rule that refuses the
call; a lint or gate check that fails the artefact; a default or path
layout that makes the wrong action unavailable; a script that performs
the step so it cannot be performed differently. What does not count:
a bolder warning, the same rule moved somewhere more prominent, a
checklist item, or a promise to be careful.

A barrier is real once it is switched on and proven, not once it is
described: prove it against the real command it must refuse and a
legitimate command from the real tool record, both run through it.
