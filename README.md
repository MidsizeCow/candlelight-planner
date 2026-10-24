# CandleLight

A planning layer for Claude Code. Before any code is written, a planner states
what it understood, what it found and what it is leaving out. You confirm or
correct each line, and a separate session builds only the version you approved.

**Status:** finished concept test. It worked as designed, but in a small replay
test it didn't catch anything plain plan mode missed, so it stops here. The
write-up covers the whole story.

## How it works

1. **Plan.** In a fresh session, run `/candlelight-plan <what you want>`. The
   planner searches the code, then writes `.candlelight/proposals/P-###.json`
   with its restatement, steps, what it is leaving out, and every assumption,
   with conflicts listed first. Reply with corrections or questions. When it's
   right, reply with the single word `approved`.
2. **Build.** Start a *new* session and run `/candlelight-build P-###`. The
   builder reads only that approved file, builds only its steps, and stops with
   a new version for you to review if anything surprises it. It never commits.

While planning, a guard hook sees every tool call. It stops the planner from
editing code, starting subagents or reading old proposal versions.

## What's in this repo

The repo mirrors what gets installed into a project:

```text
.claude/
├── hooks/candlelight_plan_guard.py        # the planner guard (the only code)
├── hooks/test_candlelight_plan_guard.py   # its unit tests
└── skills/
    ├── candlelight-plan/SKILL.md
    └── candlelight-build/SKILL.md
.gitignore                                 # .candlelight/ stays out of git
.ignore                                    # project-wide rg searches skip history/
```

## Requirements

- **macOS, Linux or WSL.** On Windows, run Claude Code inside WSL. Native
  Windows isn't supported: the guard refuses the Grep, Glob and PowerShell
  tools, and the hook calls `python3`.
- **Claude Code 2.1.295 or later**, for `onFailure: "block"` on hooks.
- **Python 3** (`python3`). If it's missing, the guard fails closed and every
  tool call in a planning session is refused.
- **ripgrep** (`rg`). It's the planner's only way to search file contents. On
  Linux, Claude Code's shell has built-in `find` and `grep` but not `rg`.
  Check with `rg --version`, and install it if it's missing:
  - macOS: `brew install ripgrep`
  - Debian, Ubuntu or WSL: `sudo apt install ripgrep`
  - Fedora: `sudo dnf install ripgrep`

## Install into a project

1. Copy `.claude/hooks/candlelight_plan_guard.py` and both folders under
   `.claude/skills/` into the project's `.claude/`.
2. Add `.candlelight/` to the project's `.gitignore` and
   `.candlelight/proposals/history/` to its `.ignore`.
3. Create `.candlelight/proposals/history/`.
4. Check where the project's data lives. rg skips dot-folders and gitignored
   folders, so the planner won't search data kept there.
5. Turn off any coding ruleset that does its own planning (for example
   `/ponytail off`) in planning sessions.

Don't add a settings deny rule for `history/`: Claude Code won't write files
covered by a Read deny rule, so both skills would fail to save old versions.

## Run the tests

```sh
python3 -m unittest discover -s .claude/hooks -p "test_*.py" -v
```

## Live check

Run this once in each project after installing.

1. In a terminal, run `rg --version`. If it isn't found, install ripgrep (see
   [Requirements](#requirements)); without it the planner can't search file
   contents.
2. In a fresh session, run `/candlelight-plan` with any request, then ask the
   planner to try each of the commands below.

All of these must be refused:

- edit a code file; Read a file in `.candlelight/proposals/history/`
- `cat .candlelight/proposals/history/<any file>`, `cat .candlelight/proposals/*/P-001*`
- `rg --hidden x`, `cp a b`, `grep -r x .`, `find . -exec cat {} \;`
- `git diff --output=x`, `git log -p`, `ls && touch x`
- Write to `.candlelight/proposals/../../x.py`
- start a subagent that edits code; run a command with the Monitor tool
- `rg X .candlelight`; `grep x README.md` (the reason should point to rg)

These must work: `rg <word>`, `ls`/`cat`/`find` on code folders,
`find . -name "*.py"` (a quoted wildcard in a name test), `git status`,
`git log`, `git diff`, `git rev-parse HEAD`, and Writes to
`.candlelight/proposals/P-001.json` and `.candlelight/proposals/history/P-001.v1.json`.
Then, in a session that never ran `/candlelight-plan`, a normal code edit must work.

## Known limits (phase 1)

- **Never resume a planning session.** Skill hooks belong to the session
  process that ran `/candlelight-plan`, so `claude --continue` or `--resume`
  brings back the planner without its guard. Start a fresh session and run
  `/candlelight-plan P-###` to pick up an existing proposal.
- **Only the planner is guarded.** In build sessions, the builder's
  instructions and `.ignore` are all that keep it out of `history/`.
- The guard allows only Read, Bash (the shell rules), file writes in
  `proposals/`, ToolSearch, AskUserQuestion, WebFetch and WebSearch. If your
  Claude Code has Grep or Glob tools, the planner can't use them; it uses rg.
  `grep` in the shell is refused too, with a pointer to rg.
- `git show` prints full patches. That's safe only because `.candlelight/` is
  never committed. Keep it out of git.
- The planner can't use `|`, `$`, `{}` or `~` in shell commands, even inside an
  rg pattern. Use `-e` once per alternative instead of `|`.
- rg can't search `.candlelight/` while planning, because rg searches paths
  it's given even when `.ignore` lists them. A search for the literal text
  `.candlelight` is refused too; `rg candlelight` works.
