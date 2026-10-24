"""Tests for the CandleLight planner guard.

Each test pipes a sample hook event into the guard, the same way Claude Code
does, and checks the result. Test names carry the row number from the
acceptance tables in the original spec.

Run from the project root:
    python3 -m unittest discover -s .claude/hooks -p "test_*.py" -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).with_name("candlelight_plan_guard.py")


class GuardTest(unittest.TestCase):
    """Base class: a throwaway project and helpers to run the guard in it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name).resolve()
        self.proposals = self.project / ".candlelight" / "proposals"
        (self.proposals / "history").mkdir(parents=True)
        (self.proposals / "P-001.json").write_text("{}")
        (self.proposals / "history" / "P-001.v1.json").write_text("{}")
        (self.project / "src").mkdir()
        (self.project / "src" / "game.py").write_text("candles = 3\n")

    def tearDown(self):
        self._tmp.cleanup()

    def run_guard(self, event, project_dir=None):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir or self.project)}
        stdin = event if isinstance(event, str) else json.dumps(event)
        return subprocess.run(
            [sys.executable, str(GUARD)],
            input=stdin, capture_output=True, text=True, env=env,
        )

    def event(self, tool_name, tool_input, cwd=None):
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "cwd": str(cwd or self.project),
        }

    def assertDenied(self, tool_name, tool_input, cwd=None):
        result = self.run_guard(self.event(tool_name, tool_input, cwd))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout, f"expected a deny, got an allow: {tool_input}")
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertTrue(output["permissionDecisionReason"].startswith("CandleLight planner: "))
        return output["permissionDecisionReason"]

    def assertAllowed(self, tool_name, tool_input, cwd=None):
        result = self.run_guard(self.event(tool_name, tool_input, cwd))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "", f"expected an allow, got: {result.stdout}")

    def assertBashDenied(self, command, cwd=None):
        return self.assertDenied("Bash", {"command": command}, cwd)

    def assertBashAllowed(self, command, cwd=None):
        self.assertAllowed("Bash", {"command": command}, cwd)


class MustBeRefused(GuardTest):
    """Spec table: must be refused in a planning session."""

    def test_01_edit_a_code_file(self):
        self.assertDenied("Edit", {
            "file_path": str(self.project / "src" / "game.py"),
            "old_string": "candles", "new_string": "time",
        })

    def test_02_read_a_history_file(self):
        self.assertDenied("Read", {"file_path": str(self.proposals / "history" / "P-001.v1.json")})
        self.assertDenied("Read", {"file_path": "history/P-001.v1.json"}, cwd=self.proposals)

    def test_03_cat_a_history_file(self):
        self.assertBashDenied("cat .candlelight/proposals/history/P-001.v1.json")

    def test_04_cat_with_wildcards(self):
        self.assertBashDenied("cat .candlelight/proposals/*/P-001*")

    def test_05_rg_hidden(self):
        self.assertBashDenied("rg --hidden candles")

    def test_06_cp(self):
        self.assertBashDenied("cp src/game.py src/copy.py")

    def test_07_grep_recursive(self):
        self.assertBashDenied("grep -r candles .")

    def test_08_find_exec(self):
        self.assertBashDenied("find . -exec cat {} \\;")
        self.assertBashDenied("find . -exec cat +")

    def test_09_git_diff_output(self):
        self.assertBashDenied("git diff --output=x")

    def test_10_git_log_patch(self):
        self.assertBashDenied("git log -p")
        self.assertBashDenied("git log --patch")

    def test_11_chained_command(self):
        self.assertBashDenied("ls && touch x")

    def test_12_write_escaping_proposals_with_dot_dot(self):
        self.assertDenied("Write", {
            "file_path": str(self.proposals / ".." / ".." / "x.py"),
            "content": "",
        })


class MustStillWork(GuardTest):
    """Spec table: must still work in a planning session."""

    def test_01_rg_across_the_code(self):
        self.assertBashAllowed("rg candles")
        self.assertBashAllowed("rg -n 'candle.*' src")

    def test_02_ls_cat_find_on_code_folders(self):
        self.assertBashAllowed("ls src")
        self.assertBashAllowed("cat src/game.py")
        self.assertBashAllowed("find src -name game.py")

    def test_03_read_only_git(self):
        self.assertBashAllowed("git status")
        self.assertBashAllowed("git status --porcelain -- src/game.py")
        self.assertBashAllowed("git log --oneline -5")
        self.assertBashAllowed("git diff")
        self.assertBashAllowed("git rev-parse HEAD")

    def test_04_write_a_proposal(self):
        self.assertAllowed("Write", {"file_path": str(self.proposals / "P-001.json"), "content": "{}"})

    def test_05_write_a_history_copy(self):
        self.assertAllowed("Write", {
            "file_path": str(self.proposals / "history" / "P-001.v1.json"),
            "content": "{}",
        })


class ExtraGapsClosed(GuardTest):
    """Gaps found while attacking the guard, beyond the original spec."""

    def test_variables_and_brace_expansion_cannot_hide_a_history_path(self):
        self.assertBashDenied("cat $PWD/.candlelight/proposals/history/P-001.v1.json")
        self.assertBashDenied("cat ${PWD}/.candlelight/proposals/history/P-001.v1.json")
        self.assertBashDenied("cat .candlelight/proposals/{history,x}/P-001.v1.json")

    def test_tilde_is_refused(self):
        self.assertBashDenied("cat ~/notes.txt")
        self.assertBashDenied("ls ~+")

    def test_rg_hidden_short_form_and_combined_flags(self):
        self.assertBashDenied("rg -. candles")
        self.assertBashDenied("rg -iu candles")
        self.assertBashDenied("rg -uuu candles")
        self.assertBashDenied("rg --unrestricted candles")

    def test_rg_flag_with_value_form(self):
        self.assertBashDenied("rg --pre=cat candles")
        self.assertBashDenied("rg --glob=*.py candles")

    def test_rg_every_no_ignore_form(self):
        self.assertBashDenied("rg --no-ignore candles")
        self.assertBashDenied("rg --no-ignore-vcs candles")

    def test_find_flags_that_write_or_run(self):
        self.assertBashDenied("find . -fls out.txt")
        self.assertBashDenied("find . -okdir cat")

    def test_git_no_index_from_inside_proposals(self):
        self.assertBashDenied(
            "git diff --no-index /dev/null history/P-001.v1.json",
            cwd=self.proposals,
        )

    def test_git_subcommand_must_follow_git(self):
        self.assertBashDenied("git -c core.pager=less log")

    def test_git_arguments_cannot_name_candlelight(self):
        self.assertBashDenied("git log -- .candlelight/proposals/P-001.json")

    def test_unquoted_wildcard_in_rg_pattern_is_refused(self):
        # Bash would expand it into several files, and every file after the
        # first becomes a path for rg to search, history included.
        self.assertBashDenied("rg .candlelight/proposals/*")

    def test_quoted_wildcard_in_rg_pattern_is_allowed(self):
        self.assertBashAllowed('rg "candle.*" src')
        self.assertBashAllowed("rg -e 'moon.*' -e 'sun' src")

    def test_quoted_wildcards_in_find_name_tests_are_allowed(self):
        self.assertBashAllowed("find src -name '*.py'")
        self.assertBashAllowed('find . -iname "*.PY"')
        self.assertBashAllowed("find . -path './src/*'")
        self.assertBashAllowed('find . -ipath "*/SRC/*"')

    def test_wildcards_elsewhere_in_find_are_refused(self):
        self.assertBashDenied("find src -name *.py")
        self.assertBashDenied("find 'src*' -name x")

    def test_history_path_hidden_in_a_flag_value(self):
        self.assertBashDenied("rg --file=.candlelight/proposals/history/P-001.v1.json src")
        self.assertBashDenied("rg -f.candlelight/proposals/history/P-001.v1.json src")

    def test_relative_paths_resolve_against_the_hook_cwd(self):
        self.assertBashDenied("cat history/P-001.v1.json", cwd=self.proposals)
        self.assertBashAllowed("cat P-001.json", cwd=self.proposals)


class RgStaysOutOfCandlelight(GuardTest):
    """rg searches paths it's given even when .ignore lists them."""

    def test_relative_path(self):
        self.assertBashDenied("rg X .candlelight")

    def test_dot_slash_path(self):
        self.assertBashDenied("rg X ./.candlelight")

    def test_absolute_path(self):
        self.assertBashDenied(f"rg X {self.project}/.candlelight")

    def test_parent_path_from_a_subfolder(self):
        self.assertBashDenied("rg X ../.candlelight", cwd=self.project / "src")

    def test_pattern_glued_to_a_flag_group(self):
        # rg reads -ieX as -i -e X, so .candlelight is a path, not the pattern.
        self.assertBashDenied("rg -ieX .candlelight")

    def test_cwd_inside_candlelight(self):
        self.assertBashDenied("rg X", cwd=self.project / ".candlelight")

    def test_whole_project_search_still_works(self):
        self.assertBashAllowed("rg X .")


class OtherTools(GuardTest):
    """The skill's matcher is "*", so the guard sees every tool."""

    def test_reading_code_and_proposals(self):
        self.assertAllowed("Read", {"file_path": str(self.project / "src" / "game.py")})
        self.assertAllowed("Read", {"file_path": str(self.proposals / "P-001.json")})

    def test_safe_tools_are_allowed(self):
        self.assertAllowed("ToolSearch", {"query": "select:WebFetch"})
        self.assertAllowed("AskUserQuestion", {"questions": []})
        self.assertAllowed("WebSearch", {"query": "hourglass emoji"})
        self.assertAllowed("WebFetch", {"url": "https://example.com", "prompt": "summary"})

    def test_subagents_and_command_runners_are_refused(self):
        self.assertDenied("Agent", {"prompt": "edit src/game.py"})
        self.assertDenied("Task", {"prompt": "edit src/game.py"})
        self.assertDenied("Monitor", {"command": "touch x"})

    def test_unknown_and_mcp_tools_are_refused(self):
        self.assertDenied("EnterWorktree", {})
        self.assertDenied("mcp__github__create_or_update_file", {"path": "x"})

    def test_notebook_edit_outside_proposals(self):
        self.assertDenied("NotebookEdit", {
            "notebook_path": str(self.project / "src" / "notes.ipynb"),
            "new_source": "",
        })

    def test_grep_points_to_rg(self):
        for command in ("grep -rn candles src", "egrep candles src/game.py", "fgrep -r candles ."):
            reason = self.assertBashDenied(command)
            self.assertIn("grep isn't available while planning. Run the same search with rg", reason)

    def test_commands_must_be_on_the_allowlist(self):
        self.assertBashDenied("python3 -c print")
        self.assertBashDenied("/bin/cat src/game.py")
        self.assertBashDenied("")


class FailsClosed(GuardTest):
    """Any error exits 2, which onFailure: block turns into a refusal."""

    def assertFailsClosed(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("CandleLight", result.stderr)

    def test_bad_json(self):
        self.assertFailsClosed(self.run_guard("not json"))

    def test_unclosed_quote(self):
        self.assertFailsClosed(self.run_guard(self.event("Bash", {"command": "rg 'candles"})))

    def test_missing_cwd(self):
        event = self.event("Bash", {"command": "ls"})
        del event["cwd"]
        self.assertFailsClosed(self.run_guard(event))

    def test_missing_project_dir(self):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        result = subprocess.run(
            [sys.executable, str(GUARD)],
            input=json.dumps(self.event("Bash", {"command": "ls"})),
            capture_output=True, text=True, env=env,
        )
        self.assertFailsClosed(result)


if __name__ == "__main__":
    unittest.main()
