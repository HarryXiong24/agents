---
name: study-plan
description: Turn a learning goal into named study sessions for one date within a total time budget, then propose them as an unsaved draft. Use when the user wants to plan study, practice, or learning time.
---

# Study plan

## Inputs

- A learning goal or subject, one date, and a total time budget in minutes.
- Ask for anything missing. Resolve relative dates such as "tomorrow" with the
  time tool, and convert hours to minutes.

## Workflow

1. Read `references/session-guide.md` with `read_skill_file` to choose how many
   sessions fit the budget.
2. Split the goal into distinct, concrete session names. Keep the user's subject
   words in every name, for example "Python: list comprehensions".
3. Call `generate_todo_draft` alone with those names, the date and the budget.
   It proposes durations, validates them and ends the turn.
4. Do not save the sessions. Saving needs a later, explicit user request.

## Limits

- One date per plan. If the user asks for several days, plan the first date and
  explain that multi-date drafts are unavailable.
- Do not invent fixed per-session durations; the draft tool proposes them.
