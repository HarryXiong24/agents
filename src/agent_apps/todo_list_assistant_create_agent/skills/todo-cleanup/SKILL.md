---
name: todo-cleanup
description: Review saved todos for likely duplicates and overloaded days, then suggest cleanup steps without changing anything. Use when the user asks to tidy, deduplicate, or clean up their todo list.
---

# Todo cleanup

## Workflow

1. Call `list_todos` once. Add a date filter only when the user named a date.
2. Using only the returned records, group likely duplicates: the same date with
   names that differ only in case, spacing, punctuation or obvious wording.
3. Flag days whose listed durations clearly exceed 480 minutes (8 hours). Use
   `calculate` when an exact total matters to the answer.
4. Present suggestions: which record to keep and which to update or delete.
   If nothing looks duplicated or overloaded, say so.

## Safety

- This workflow is read-only. Do not call `save_todo` or `delete_todo` while
  presenting suggestions.
- Change records only after the user explicitly asks for a specific change.
  Each deletion still goes through console approval.
