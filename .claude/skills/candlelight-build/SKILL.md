---
name: candlelight-build
description: Build an approved CandleLight proposal exactly as approved.
disable-model-invocation: true
argument-hint: [proposal ID, e.g. P-007]
---

# CandleLight builder

If no proposal ID was given, ask which proposal to build and wait.

You are building, not planning. Build exactly what proposal
$ARGUMENTS says, nothing more, and stop the moment something
doesn't match.

## Rules that always apply
1. Build only proposal $ARGUMENTS. Read only
   .candlelight/proposals/$ARGUMENTS.json. Never open
   .candlelight/proposals/history/.
2. Build only what is in the proposal's steps. Never build
   anything listed in left_out, and never add anything that
   isn't in the steps.
3. Never change the plan yourself. If it is wrong, incomplete or
   out of date, stop and send it back (see the Surprises section
   below).
4. Never commit, push or change git history. The user commits.
5. If a coding ruleset is active (such as Ponytail), it decides
   how to write the code. These rules decide what to build. If
   the two conflict, stop and ask.
6. If the user's reply contains a question, answer it and wait.

## Verify
Check all of these before touching any code. If one fails,
stop, say which one and why, and wait.
- The file .candlelight/proposals/$ARGUMENTS.json exists.
- status is approved. If not: "$ARGUMENTS isn't approved yet.
  Finish it in a planning session first."
- approved_version equals version. If not, the plan changed
  after approval: ask the user to re-approve it in a planning
  session.
- approved_commit is present.
- The code hasn't moved: run
  git diff --stat <approved_commit> -- <every file in concepts_touched>
  and git status --porcelain -- <every file in concepts_touched>
  (the diff alone misses new untracked files).
  If any of those files changed since approval, treat it as a
  surprise (see the Surprises section below).

When every check passes, set status to building, tell the user
in a line or two what you will build (the proposal's steps) and
what you won't (left_out), then start.

## Build
- Work through the proposal's steps in order. Skip steps listed
  in steps_done after a quick check that they really are in the
  code; if one isn't, that's a surprise.
- Change only files listed in concepts_touched, plus new files a
  step says to create. If a step needs any other file, that's a
  surprise (see the Surprises section below).
- Don't refactor, rename, reformat or clean up anything outside
  the steps, even if it looks wrong. Note it for the Finish
  summary instead.
- Keep track of which steps are done, so a stop or finish can
  report exactly where you got to.
- If the project has tests, run them after the last step. Report
  the results. Don't fix failures unrelated to the steps; note
  them.

## Surprises
A surprise is anything the proposal didn't cover: a file outside
concepts_touched, code that works differently than an assumption
says, a step that can't work as written, or changed files found
in Verify.

When one happens:
1. Stop before acting on it. Never work around it.
2. Copy the proposal to
   .candlelight/proposals/history/$ARGUMENTS.v<version>.json.
3. Write a new version of the proposal:
   - raise version by one and set status to needs_you
   - remove approved_version and approved_commit
   - add an assumption with state conflict and
     found_during_build: true. In note: what you found, what you
     wanted to do, and why you stopped
   - set steps_done to the numbers of the steps you finished
4. Leave finished work in place, uncommitted. The re-plan can't
   be approved until the user commits or discards it.
5. Tell the user what you found and why you stopped, then:
   "Start a planning session and run /candlelight-plan P-###
   to review it."

## Finish
When every one of the proposal's steps is done:
1. Set status to done, steps_done to every step, and
   files_changed to every file you changed or created.
2. Tell the user, briefly:
   - what was built, step by step
   - every file changed or created
   - anything you noticed outside the steps but didn't touch
   - test results, if the project has tests
   - anything skipped, and why
3. Remind them nothing is committed: "Review the changes, then
   commit when you're ready."

Never start another proposal or extra work in this session.
