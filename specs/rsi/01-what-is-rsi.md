# 1. What Is Recursive Self-Improvement?

*Written so a high-school student can follow it. No maths beyond averages.*

## The one-sentence version

**Recursive self-improvement (RSI)** is when a system uses its own abilities to make
itself better — and then uses that *better* version to make the next improvement, and so
on, round after round.

The word **recursive** just means "the output goes back in as the input."

## Example 1: The student who studies how to study

Maya has a maths test every Friday.

- **Normal improvement:** Maya studies more each week. Her grade goes up. Her *study
  method* stays the same.
- **Self-improvement:** After each test, Maya looks at which questions she got wrong and
  changes *how* she studies — more practice problems, fewer re-reads of notes. Her grade
  goes up because her method got better.
- **Recursive self-improvement:** Maya also starts noticing *how she decides* which
  study changes to try. She learns that changes she tests for two weeks are more
  reliable than changes she judges after one lucky test. Now her *way of improving* is
  improving too. Each round, she gets better at getting better.

That last step — improving the improver — is the "recursive" part.

## Example 2: A tool that builds better tools

A blacksmith makes a hammer out of a rock. With the hammer, she can make a better
hammer. With that better hammer, she can make tongs, an anvil, and an even better hammer.
Each tool makes the next tool easier to make. Nobody had to hand her a factory; she
climbed there, one tool at a time.

Compilers did this for real: early compilers were written in assembly, and later
compilers were written *in the language they compile*, built by the previous compiler
("bootstrapping").

## The loop at the heart of every RSI system

Every example in this folder — snakes, chess programs, Google's AlphaEvolve — runs the
same four-step loop:

```
   ┌──────────────┐
   │ 1. PROPOSE   │  Try a change ("what if I turned toward enemies sooner?")
   └──────┬───────┘
          ▼
   ┌──────────────┐
   │ 2. TEST      │  Play games with the change and without it, on the same setups
   └──────┬───────┘
          ▼
   ┌──────────────┐
   │ 3. DECIDE    │  Keep it only if it really did better — not just got lucky
   └──────┬───────┘
          ▼
   ┌──────────────┐
   │ 4. REMEMBER  │  Save the winner; it becomes the starting point AND a future rival
   └──────┬───────┘
          └────────► back to 1, starting from the new, better version
```

If you remember one thing from this folder, remember this loop.

## Three levels of "self-improvement"

| Level | What changes | Everyday example | In Snake Arena |
|---|---|---|---|
| **1. Tuning** | Numbers inside a fixed strategy | Adjusting how long you boil pasta | A snake changes "how much do I fear walls?" from 3.0 to 4.5 |
| **2. Rewriting** | The strategy itself | Switching from boiling to baking | A snake's code is rewritten to add a new tactic (later, optional, needs a sandbox) |
| **3. Improving the improver** | How changes are proposed and judged | Learning to taste-test properly before changing a recipe | The search adapts its own step size from what got accepted |

Snake Arena does level 1 and part of level 3 in phases 3–4. Level 2 is an optional
extension. **Nobody in this project changes the AI model itself** — we improve the
snakes' *strategies*, the way a coach improves a team's playbook without changing the
players' DNA.

## Why the "DECIDE" step is the whole game

Imagine flipping a coin 10 times and getting 7 or more heads. Is the coin unfair? Probably not —
that happens by luck about 1 time in 6. Now imagine you try 20 random "improvements" to
your snake and test each for one game. Some of them *will* look great purely by luck.
Keep those, and your snake gets worse while your scoreboard says it's getting better.

So a real RSI system needs:

- **Many tests, not one.** (We use 100 paired games per decision.)
- **Fair comparisons.** Test the old and new version on the *exact same* starting
  positions, so luck cancels out.
- **A fresh exam.** Check the winner on games it was never tuned on (a *holdout*), like a
  teacher giving a new test instead of re-using the practice questions.
- **A judge the student can't bribe.** The snake can change its strategy but can never
  change the scoring rules or the test. More on this in
  [`04-pitfalls.md`](04-pitfalls.md).

## Where the idea comes from

- **1965 — I. J. Good** imagined an "ultraintelligent machine" that could design even
  better machines, leading to an "intelligence explosion." That is the dramatic version
  of RSI.
- **2003 — Jürgen Schmidhuber's Gödel Machine**: a theoretical program that rewrites any
  part of its own code, but *only after proving* the rewrite is an improvement. Beautiful,
  but proofs like that are almost impossible in practice.
- **2017 — AlphaZero** taught itself chess and Go from scratch by playing against
  earlier versions of itself, keeping a new version only if it beat the old one.
- **2023 — STOP (Self-Taught Optimizer)**: a program that uses a language model to
  improve code was pointed at *its own code* and got better at improving code.
- **2025 — Darwin Gödel Machine** and **AlphaEvolve**: systems that keep an archive of
  program versions, propose edits with a language model, and keep what tests show works.
  Details and sources in [`03-algorithms.md`](03-algorithms.md).

The modern lesson: **replace "prove it's better" with "test it's better, carefully."**
That's exactly what Snake Arena does.
