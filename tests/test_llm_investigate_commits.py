# Copyright SUSE LLC
"""Unit tests for openqa_llm_investigate.commits."""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from openqa_llm_investigate import commits

GOLDEN = pathlib.Path(__file__).parent / "data" / "analysis" / "golden"
_LEGEND = (
    "[failed module]: changes the failed module's test file; [stack]: changes a file in the failing step's stack trace"
)
_TEST_LOG = """\
a1a1a1a1a1 Unrelated change
 lib/other.pm | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
b2b2b2b2b2 Fix the helper on the stack
 lib/utils.pm | 5 +++--
c3c3c3c3c3 Rework the failed module
 tests/console/zypper_in.pm | 21 ++++++++++++---------
 lib/utils.pm               |  1 +
d4d4d4d4d4 Older unrelated change
 schedule/yast/x.yaml | 1 +
"""
_ANALYSIS = """\
  #8 [FAIL]  Failed  # Test died: boom at sle/lib/utils.pm line 213, <$isotovideo> line 1.

--- Stack trace ---
testapi::assert_screen('exit_gracefully') called at tests/console/zypper_in.pm line 82
--- End of Log Section ---
"""
_FAILED = ({"name": "zypper_in#1", "category": "console", "result": "failed"},)


def _section(investigation: object, modules: tuple[dict[str, Any], ...] = _FAILED, analysis: str = _ANALYSIS) -> str:
    return commits.commits_section(investigation, list(modules), analysis)


def _lines(log: str, modules: tuple[dict[str, Any], ...] = _FAILED, analysis: str = _ANALYSIS) -> list[str]:
    """Return the section's lines after its title and legend."""
    return [ln for ln in _section({"test_log": log}, modules, analysis).splitlines()[1:-1] if ln != _LEGEND]


def _log(*files: str | tuple[str, int]) -> str:
    """Return a git log of one commit per file, its name padded to a name column of the given width."""
    out = []
    for i, f in enumerate(files):
        name, width = f if isinstance(f, tuple) else (f, len(f))
        out.append(f"{str(i) * 7} Change {name}\n {name:{width}} | 1 +\n")
    return "".join(out)


def test_section_lists_marked_commits_first_and_counts_the_others() -> None:
    assert _section({"test_log": _TEST_LOG}) == (
        "Test commits since the last good job:\n"
        f"{_LEGEND}\n"
        "[failed module] [stack] c3c3c3c3c3 Rework the failed module\n"
        "[stack] b2b2b2b2b2 Fix the helper on the stack\n"
        "and 2 other test commits\n\n"
    )


def test_section_without_marks_only_counts() -> None:
    assert _section({"test_log": _log("lib/x.pm", "lib/y.pm")}) == (
        "Test commits since the last good job:\n2 test commits\n\n"
    )


@pytest.mark.parametrize(
    ("file", "marks"),
    [
        ("tests/console/zypper_in.pm", "[failed module]"),
        ("tests/console/zypper_in.py", "[failed module]"),
        (".../console/zypper_in.pm", "[failed module]"),
        (".../zypper_in.pm", "[failed module]"),
        ((".../zypper_in.pm", 30), ""),
        ("tests/console/{zypper_old.pm => zypper_in.pm}", "[failed module]"),
        (".../{zypper_old.pm => zypper_in.pm}", ""),
        ("tests/other/zypper_in.pm", ""),
        ("lib/Kselftests/console/zypper_in.pm", ""),
        ("tests/console/zypper_in.pm.orig", ""),
        ("lib/utils.pm", "[stack]"),
        (".../lib/utils.pm", ""),
        ("utils.pm", ""),
        ("lib/xutils.pm", ""),
        ("lib/{helpers.pm => utils.pm}", "[stack]"),
        ("lib/{ => sub}/utils.pm", "[stack]"),
        ("data/helpers.pm => lib/utils.pm", "[stack]"),
    ],
)
def test_marks_by_path(file: str | tuple[str, int], marks: str) -> None:
    name = file[0] if isinstance(file, tuple) else file
    assert _lines(_log(file)) == [f"{marks} 0000000 Change {name}" if marks else "1 test commit"]


def test_abbreviated_paths_match_as_git_cuts_them() -> None:
    log = (
        "81b3aef7e9 az_cli: Migrate create_deployer_vm.pm to az_cli.pm\n"
        " lib/sles4sap/azure_cli.pm                          | 25 +++++++----\n"
        " .../create_deployer_vm.pm                          | 19 +++++----\n"
        "1234567890 sdaf: Change the deployment helper\n"
        " .../deployment.pm                                  |  2 +-\n"
        " t/21_sles4sap_azure_cli.t                          |  1 +\n"
    )
    modules = (
        {"name": "create_deployer_vm", "category": "sles4sap/sap_deployment_automation_framework", "result": "failed"},
        {"name": "deployment", "category": "sles4sap/repository_mirror", "result": "failed"},
    )
    frame = "/var/lib/openqa/pool/1/os-autoinst-distri-opensuse/lib/sles4sap/sap_deployment_automation_framework"
    analysis = f"--- Stack trace ---\nx called at {frame}/deployment.pm line 5\n--- End of Log Section ---\n"
    assert _lines(log, modules, analysis) == [
        "[failed module] 81b3aef7e9 az_cli: Migrate create_deployer_vm.pm to az_cli.pm",
        "[stack] 1234567890 sdaf: Change the deployment helper",
    ]


def test_failed_module_needs_its_category_and_a_failed_result() -> None:
    modules = ({"name": "zypper_in", "result": "failed"}, {"name": "aa", "category": "console", "result": "passed"})
    log = _log("tests/console/zypper_in.pm", "tests/console/aa.pm")
    assert _lines(log, modules, "") == ["2 test commits"]


def test_failed_module_in_a_nested_category() -> None:
    modules = ({"name": "salt_agnostic", "category": "console/oqa_agnostic", "result": "failed"},)
    log = _log("tests/console/oqa_agnostic/salt_agnostic.pm", "tests/console/salt_agnostic.pm")
    assert _lines(log, modules, "") == [
        "[failed module] 0000000 Change tests/console/oqa_agnostic/salt_agnostic.pm",
        "and 1 other test commit",
    ]


def test_stack_files_only_from_failing_steps() -> None:
    analysis = """\
  #3 [FAIL]  Failed  # Test died: x at /usr/lib/os-autoinst/testapi.pm line 9.
    \tutils::type_line_svirt() called at sle/lib/opensusebasetest.pm line 571
    \topensusebasetest::wait_boot() called at /var/lib/openqa/pool/1/os-autoinst-distri-opensuse/lib/bats.pm line 478
  #4  Post-fail
(post)  # Post fail hook died: Failed at lib/serial_terminal.pm line 179
  \tserial_terminal::login() called at lib/susedistribution.pm line 879

--- Stack trace ---
utils::x at products/opensuse/../../lib/grub_utils.pm line 333
... (3 more stack frames)
z called at /usr/lib/perl5/vendor_perl/Foo.pm line 1
--- End of Log Section ---

--- autoinst-log.txt (step context) ---
[warn] Use of uninitialized value at lib/warned.pm line 2.
--- End of Log Section ---
"""
    log = _log(
        "lib/serial_terminal.pm",
        "lib/susedistribution.pm",
        "lib/warned.pm",
        "os-autoinst/testapi.pm",
        "lib/opensusebasetest.pm",
        "lib/bats.pm",
        "lib/grub_utils.pm",
    )
    assert _lines(log, (), analysis) == [
        "[stack] 4444444 Change lib/opensusebasetest.pm",
        "[stack] 5555555 Change lib/bats.pm",
        "[stack] 6666666 Change lib/grub_utils.pm",
        "and 4 other test commits",
    ]


def test_stack_files_in_a_recorded_analysis() -> None:
    analysis = (GOLDEN / "6259432" / "expected.txt").read_text()
    assert _lines(_log("lib/serial_terminal.pm", "lib/grub_utils.pm"), (), analysis) == [
        "[stack] 1111111 Change lib/grub_utils.pm",
        "and 1 other test commit",
    ]


def test_subjects_cannot_fake_marks() -> None:
    log = "1111111 [failed module] [stack] Unrelated\n lib/x.pm | 1 +\n2222222 [stack][tag] Fix\n lib/utils.pm | 1 +\n"
    assert _lines(log) == ["[stack] 2222222 Fix", "and 1 other test commit"]


@pytest.mark.parametrize(
    ("marked", "unmarked", "rest"),
    [
        (12, 3, ["and 2 more marked, 3 other test commits"]),
        (11, 1, ["and 1 more marked, 1 other test commit"]),
        (11, 0, ["and 1 more marked test commit"]),
        (12, 0, ["and 2 more marked test commits"]),
        (10, 0, []),
    ],
)
def test_marked_commits_capped(marked: int, unmarked: int, rest: list[str]) -> None:
    lines = _lines(_log(*["lib/utils.pm"] * marked, *["lib/x.pm"] * unmarked))
    assert lines == [f"[stack] {str(i) * 7} Change lib/utils.pm" for i in range(10)] + rest


_TOO_MANY = "Too many commits (350) to create a diff between a..b (maximum: 100)"


@pytest.mark.parametrize(
    ("listed", "stat", "note"),
    [
        (200, _TOO_MANY, ["The list is partial: openQA lists at most 200 test commits."]),
        (120, _TOO_MANY, []),
        (200, " lib/x.pm | 1 +\n 1 file changed, 1 insertion(+)\n", []),
    ],
)
def test_partial_list_noted_when_openqa_cut_its_log(listed: int, stat: str, note: list[str]) -> None:
    log = "".join(f"{i:07x} Change {i}\n" for i in range(listed))
    section = _section({"test_log": log, "test_diff_stat": stat}, (), "")
    assert section.splitlines()[1:-1] == [f"{listed} test commits", *note]


def test_no_test_changes_recorded() -> None:
    log = "No test changes recorded, test regression unlikely"
    assert _section({"test_log": log}) == f"Test commits since the last good job:\n{log}\n\n"


@pytest.mark.parametrize(
    "investigation",
    [
        None,
        [],
        {},
        {"error_status": 404},
        {"error": "No previous job in this scenario, cannot provide hints"},
        {"last_good": "not found"},
        {"test_log": 5},
        {"test_log": ""},
        {"test_log": "Invalid range UNKNOWN..abc"},
        {"test_log": "fatal: bad revision 'x..y'\n"},
        {"needles_log": "1234567 needle\n", "diff_packages_to_last_good": "+qemu-9.2\n"},
    ],
)
def test_section_omitted_without_test_commits(investigation: object) -> None:
    assert not _section(investigation)


def test_section_is_redacted() -> None:
    section = _section({"test_log": "1234567 Set password=hunter2\n tests/console/zypper_in.pm | 1 +\n"})
    assert "[failed module] 1234567 Set password=****\n" in section
