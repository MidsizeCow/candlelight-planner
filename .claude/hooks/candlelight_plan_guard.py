#!/usr/bin/env python3
"""CandleLight planner guard.

A PreToolUse hook that /candlelight-plan registers, for every tool, for the
rest of the planning session. It is an allowlist: any tool or command not
explicitly allowed is denied. The planner may read and search the code and
write proposals, but may never edit code or see old proposal versions in
.candlelight/proposals/history/.

  Allow: exit 0 with no output, so the normal permission flow applies.
  Deny:  exit 0 with a PreToolUse "deny" decision on stdout.
  Error: exit 2 with the reason on stderr. The skill sets onFailure: block,
         so any failure refuses the call instead of letting it through.

Each rule says why it exists, in the comments below.
Python standard library only.
"""

import json
import os
import sys
from pathlib import Path

FILE_TOOLS = {"Edit", "Write", "NotebookEdit"}
# Tools that can't change anything. Every tool not named here, in FILE_TOOLS,
# or handled below (Read, Bash) is refused: subagents, Monitor, MCP tools, and
# any tool added to Claude Code later.
SAFE_TOOLS = {"ToolSearch", "AskUserQuestion", "WebFetch", "WebSearch"}

# Shell syntax that chains commands, redirects output, or makes bash expand
# text into something the checks below never saw ($VAR, {a,b}, ~).
FORBIDDEN_CHARS = [";", "&", "|", "`", ">", "<", "\n", "$", "{", "}", "~"]

ALLOWED_COMMANDS = {"rg", "ls", "cat", "find"}
GREP_COMMANDS = {"grep", "egrep", "fgrep"}  # refused with a pointer to rg
ALLOWED_GIT_SUBCOMMANDS = {"log", "diff", "show", "status", "rev-parse"}

DENIED_FLAGS = {
    "ls": set(),
    "cat": set(),
    # Run other commands, delete files, or write files.
    "find": {"-exec", "-execdir", "-ok", "-okdir", "-delete",
             "-fprint", "-fprint0", "-fprintf", "-fls"},
    # Write a file, print patches, or read files git doesn't track.
    "git": {"--output", "-p", "--patch", "--no-index"},
    # Run a preprocessor, or widen the search past hidden and ignored files.
    "rg": {"--pre", "--hidden", "--unrestricted", "--glob", "--iglob"},
}
RG_DENIED_PREFIX = "--no-ignore"  # every form: --no-ignore-vcs, --no-ignore-dot, ...
RG_DENIED_SHORT = set("u.g")      # -u/-uu/-uuu, -. (hidden), -g (glob), even in a group like -iu

WILDCARDS = set("*?[")
FIND_NAME_TESTS = {"-name", "-iname", "-path", "-ipath"}  # match names only, never content

ALLOWED_LIST = "rg, ls, cat, find, and git log, diff, show, status or rev-parse"
GREP_REASON = ("grep isn't available while planning. "
               "Run the same search with rg (same pattern; it skips ignored files).")
RG_CANDLELIGHT_REASON = ("rg can't search .candlelight/ while planning. "
                         "Read the current proposal with the Read tool.")
HISTORY_REASON = (".candlelight/proposals/history/ holds old versions and is off-limits. "
                  "Use the current proposal in .candlelight/proposals/ instead.")


def main():
    event = json.load(sys.stdin)
    project = Path(os.environ["CLAUDE_PROJECT_DIR"]).resolve()
    proposals = project / ".candlelight" / "proposals"
    reason = check(event["tool_name"], event.get("tool_input") or {}, Path(event["cwd"]), proposals)
    if reason:
        print(json.dumps(deny(reason)))


def check(tool_name, tool_input, cwd, proposals):
    """Return why the call is denied, or None to allow it."""
    history = proposals / "history"
    if tool_name in FILE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        return check_file_tool(path, cwd, proposals)
    if tool_name == "Read":
        path = tool_input.get("file_path")
        return None if path and not resolve(cwd, path).is_relative_to(history) else HISTORY_REASON
    if tool_name == "Bash":
        return check_bash(tool_input["command"], cwd, proposals.parent, history)
    if tool_name in SAFE_TOOLS:
        return None
    return (f"{tool_name} isn't available while planning. Look around with the Read tool "
            f"or {ALLOWED_LIST}, and put what you'd do with {tool_name} in the proposal.")


def check_file_tool(path, cwd, proposals):
    if path and resolve(cwd, path).is_relative_to(proposals):
        return None
    return ("you can only write files in .candlelight/proposals/ while planning. "
            "Put the code change in the proposal's steps; the builder makes it after approval.")


def check_bash(command, cwd, candlelight, history):
    """Shell checks, in order."""
    found = [c for c in FORBIDDEN_CHARS if c in command]
    if found:
        shown = " ".join("newline" if c == "\n" else c for c in found)
        return (f"shell commands can't contain {shown} while planning. Run one plain command "
                "at a time. In an rg pattern, use -e once per alternative instead of |.")

    words, bare = split_words(command)
    if not words:
        return f"empty command. Run one of: {ALLOWED_LIST}."
    program, args, bare_args = words[0], words[1:], bare[1:]

    if program in GREP_COMMANDS:
        return GREP_REASON
    if program not in ALLOWED_COMMANDS and not is_allowed_git(words):
        return (f"only {ALLOWED_LIST} can run while planning. Use one of those, "
                "or the Read tool, to look around. List files with rg --files.")

    for arg in args:
        if is_denied_flag(program, arg):
            return f"{arg} isn't allowed with {program} while planning. Run the command without it."

    if program == "git" and any(".candlelight" in arg for arg in args):
        return ("git can't touch .candlelight/ while planning. "
                "Read the current proposal with the Read tool instead.")

    patterns = quoted_pattern_positions(program, args)
    for i, arg in enumerate(args):
        if not WILDCARDS & set(arg):
            continue
        # A quoted wildcard in rg's pattern or a find name test is a pattern,
        # not a filename. Unquoted, bash would expand it into files first.
        if i in patterns and not WILDCARDS & set(bare_args[i]):
            continue
        return ("wildcards (*, ? or [) aren't allowed in shell arguments while planning. "
                "Name files exactly, list them with rg --files, and quote rg search patterns.")

    for arg in args:
        if any(resolve(cwd, p).is_relative_to(history) for p in path_candidates(arg)):
            return HISTORY_REASON

    # rg searches paths it's given even when .ignore lists them. Every argument
    # is checked, pattern included: in "rg -ieX .candlelight" the pattern is
    # glued to -e, so the path is the first plain argument.
    if program == "rg" and (
        cwd.resolve().is_relative_to(candlelight)
        or any(resolve(cwd, p).is_relative_to(candlelight) for arg in args for p in path_candidates(arg))
    ):
        return RG_CANDLELIGHT_REASON

    return None


def split_words(command):
    """Split a command into words the way bash would.

    Only quotes, backslashes and spaces are handled: everything else bash
    treats specially is already refused by FORBIDDEN_CHARS. Returns two
    lists: each word, and the characters of each word that were not quoted.
    """
    words, bare = [], []
    word, word_bare, in_word, quote = "", "", False, None
    chars = iter(command)
    for ch in chars:
        if quote == "'":
            if ch == "'":
                quote = None
            else:
                word += ch
        elif quote == '"':
            if ch == '"':
                quote = None
            elif ch == "\\":
                nxt = next(chars, "")
                word += nxt if nxt in '"\\' else ch + nxt
            else:
                word += ch
        elif ch in " \t":
            if in_word:
                words.append(word)
                bare.append(word_bare)
                word, word_bare, in_word = "", "", False
        elif ch in "'\"":
            quote, in_word = ch, True
        elif ch == "\\":
            nxt = next(chars, None)
            if nxt is None:
                raise ValueError("command ends with a backslash")
            word, in_word = word + nxt, True
        else:
            word, word_bare, in_word = word + ch, word_bare + ch, True
    if quote:
        raise ValueError("command has an unclosed quote")
    if in_word:
        words.append(word)
        bare.append(word_bare)
    return words, bare


def is_allowed_git(words):
    # The subcommand must come right after git, so "git -c x=y log" is refused.
    return words[0] == "git" and len(words) > 1 and words[1] in ALLOWED_GIT_SUBCOMMANDS


def is_denied_flag(program, arg):
    name = arg.split("=", 1)[0]
    if name in DENIED_FLAGS[program]:
        return True
    if program == "rg":
        if name.startswith(RG_DENIED_PREFIX):
            return True
        is_short_group = arg.startswith("-") and not arg.startswith("--")
        return is_short_group and bool(RG_DENIED_SHORT & set(arg[1:]))
    return False


def quoted_pattern_positions(program, args):
    """Arguments that may hold quoted wildcards.

    rg: its search pattern (the first non-flag argument, and every -e / --regexp
    value). find: the value of each name test (-name, -iname, -path, -ipath).
    """
    if program == "find":
        return {i + 1 for i, arg in enumerate(args) if arg in FIND_NAME_TESTS}
    if program != "rg":
        return set()
    positions = {i + 1 for i, arg in enumerate(args) if arg in ("-e", "--regexp")}
    first = next((i for i, arg in enumerate(args) if not arg.startswith("-")), None)
    if first is not None:
        positions.add(first)
    return positions


def path_candidates(arg):
    """Every way an argument can name a path: as is, after =, or glued to a short flag."""
    yield arg
    if "=" in arg:
        yield arg.split("=", 1)[1]
    if arg.startswith("-") and not arg.startswith("--"):
        yield arg[2:]


def resolve(cwd, path):
    return (cwd / path).resolve()


def deny(reason):
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"CandleLight planner: {reason}",
    }}


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"CandleLight planner guard failed, so this call is blocked: {error!r}", file=sys.stderr)
        sys.exit(2)
