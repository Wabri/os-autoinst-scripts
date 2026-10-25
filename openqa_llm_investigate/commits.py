# Copyright SUSE LLC
"""Find the test commits since the last good job that touch a failed module or the failing step's stack trace."""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

from .analysis import SECTION_END, STACK_TRACE, TEST_DIED, section_start
from .text import redact

if TYPE_CHECKING:
    from .http import JsonDict

_COMMIT_RE = re.compile(r"^([0-9a-f]{7,40})(?: (.*))?$")
_STAT_RE = re.compile(r"^ (\S[^|]{0,400}?) +\| ")
_RENAME_RE = re.compile(r"^(.*)\{(.*) => (.*)\}(.*)$")
_FRAME_RE = re.compile(r"\bat (\S{1,400}) line \d+")
_NOT_TEST_CODE_RE = re.compile(r"^/usr/|/os-autoinst/|/perl5/")
_TOO_MANY_RE = re.compile(r"^Too many commits \(\d+\) .*\(maximum: (\d+)\)$")
_NO_CHANGES_RE = re.compile(r"^No test changes recorded")
_LEADING_TAGS_RE = re.compile(r"^(?:\[[^\]\n]*\]\s*)+")
_REPEAT_RE = re.compile(r"#\d+$")
_ABBREVIATED = ".../"
_ELLIPSIS = "..."
_RENAME = " => "
_FAILED_MODULE = "[failed module]"
_STACK = "[stack]"
_TITLE = "Test commits since the last good job:"
_LEGEND = (
    f"{_FAILED_MODULE}: changes the failed module's test file;"
    f" {_STACK}: changes a file in the failing step's stack trace"
)
_MAX_SHOWN = 10


def _stack_files(analysis: str) -> list[str]:
    """Return the files in the stack frames of the failing steps of the analysis, except os-autoinst and Perl.

    Frames come from the stack trace sections and from each `# Test died` message with the frame lines indented
    below it, not from post-fail hooks or other log lines.
    """
    found: list[str] = []
    in_trace = in_died = False
    start = section_start(STACK_TRACE)
    for ln in analysis.splitlines():
        in_trace = ln == start or (in_trace and ln != SECTION_END)
        in_died = TEST_DIED in ln or (in_died and ln[:1].isspace() and bool(_FRAME_RE.search(ln)))
        if in_trace or in_died:
            found += [posixpath.normpath(m.group(1)) for m in _FRAME_RE.finditer(ln)]
    return [f for f in dict.fromkeys(found) if not _NOT_TEST_CODE_RE.search(f)]


def _module_files(testresults: list[JsonDict]) -> set[str]:
    """Return the test files `tests/<category>/<name>.pm` and `.py` of the failed modules."""
    return {
        f"tests/{m['category']}/{_REPEAT_RE.sub('', m['name'])}{ext}"
        for m in testresults
        if m.get("result") == "failed" and m.get("category") and m.get("name")
        for ext in (".pm", ".py")
    }


def _commits(log: str) -> list[tuple[str, str, list[tuple[str, int]]]]:
    """Return the hash, subject and changed files of each commit in a `git log --stat --pretty=oneline` text.

    A file is its name as `--stat` shows it and the width of the name column, which git cut longer names to.
    """
    found: list[tuple[str, str, list[tuple[str, int]]]] = []
    for ln in log.splitlines():
        if m := _COMMIT_RE.match(ln):
            found.append((m.group(1), m.group(2) or "", []))
        elif found and (m := _STAT_RE.match(ln)):
            found[-1][2].append((m.group(1), ln.index(" | ") - 1))
    return found


def _abbreviated(path: str, width: int) -> str:
    """Return `path` as `--stat` shows it in a name column of `width`: if longer, its tail behind `...`.

    git (diff.c `show_stats`) keeps the last `width - 3` characters, from their first `/` on if there is one.
    """
    if len(path) <= width:
        return path
    kept = path[len(path) - max(width - len(_ELLIPSIS), 0) :]
    return _ELLIPSIS + (kept[kept.index("/") :] if "/" in kept else kept)


def _tails(path: str) -> list[str]:
    """Return the tails of `path` that have at least two components."""
    parts = path.split("/")
    return ["/".join(parts[i:]) for i in range(len(parts) - 1)]


def _sides(name: str) -> list[str]:
    """Return the old and new path of a rename as `--stat` shows it, `a/{x => y}/b` or `x => y`."""
    if m := _RENAME_RE.match(name):
        head, old, new, tail = m.groups()
        return [re.sub(r"/+", "/", head + side + tail) for side in (old, new)]
    return name.split(_RENAME, 1)


def _same_side(side: str, path: str, *, prefixed: bool) -> bool:
    """Return whether one side of a rename is `path`; cut to `.../<tail>` or if `prefixed`, by a 2-component tail."""
    tail = side.removeprefix(_ABBREVIATED)
    if tail == side and not prefixed:
        return path == side
    return tail in _tails(path)


def _is_file(name: str, width: int, path: str, *, prefixed: bool) -> bool:
    """Return whether the `--stat` entry `name`, shown in a name column of `width`, is the file `path`.

    A `prefixed` path (absolute or relative to a parent of the test repository) matches by a tail of at least two
    components, which git must show as `name` at `width`.
    """
    if _RENAME in name:
        return any(_same_side(side, path, prefixed=prefixed) for side in _sides(name))
    return any(name == _abbreviated(p, width) for p in (_tails(path) if prefixed else [path]))


def _marks(files: list[tuple[str, int]], module_files: set[str], frames: list[str]) -> list[str]:
    """Return the marks of a commit changing a failed module's test file or another file of the stack frames."""
    modules = [f for f in files if any(_is_file(*f, m, prefixed=False) for m in module_files)]
    marks = [_FAILED_MODULE] if modules else []
    stack = any(_is_file(*f, frame, prefixed=True) for f in files if f not in modules for frame in frames)
    return [*marks, _STACK] if stack else marks


def _plural(n: int) -> str:
    """Return `test commit` or `test commits` to follow a count of `n`."""
    return "test commit" if n == 1 else "test commits"


def _rest(more: int, others: int) -> list[str]:
    """Return the line counting the marked commits beyond the shown ones and the unmarked ones, if there are any."""
    counts = [f"{n} {what}" for n, what in ((more, "more marked"), (others, "other")) if n]
    return [f"and {', '.join(counts)} {_plural(others or more)}"] if counts else []


def _partial_note(stat: object, listed: int) -> list[str]:
    """Return a note when openQA's git log stopped at its limit, which is twice the diff maximum it reports."""
    m = _TOO_MANY_RE.match(stat) if isinstance(stat, str) else None
    limit = 2 * int(m.group(1)) if m else 0
    return [f"The list is partial: openQA lists at most {limit} test commits."] if limit and listed >= limit else []


def commits_section(investigation: object, testresults: list[JsonDict], analysis: str) -> str:
    """Return the prompt section on the test commits since the last good job (empty if openQA lists none).

    `investigation` is the answer of `/tests/<id>/investigation_ajax`. The commits that change the test file of a
    failed module in `testresults` or a file in the stack frames of the failing steps in `analysis` are listed,
    the others only counted.
    """
    if not isinstance(investigation, dict) or not isinstance(log := investigation.get("test_log"), str):
        return ""
    if _NO_CHANGES_RE.match(log):
        return redact(f"{_TITLE}\n{log.strip()}\n\n")
    if not (commits := _commits(log)):
        return ""
    module_files, frames = _module_files(testresults), _stack_files(analysis)
    marked = [
        (marks, sha, subject) for sha, subject, files in commits if (marks := _marks(files, module_files, frames))
    ]
    marked.sort(key=lambda c: _FAILED_MODULE not in c[0])
    shown = [" ".join([*marks, sha, _LEADING_TAGS_RE.sub("", subject)]) for marks, sha, subject in marked[:_MAX_SHOWN]]
    more, others = len(marked) - len(shown), len(commits) - len(marked)
    lines = [_TITLE, _LEGEND, *shown, *_rest(more, others)] if shown else [_TITLE, f"{others} {_plural(others)}"]
    lines += _partial_note(investigation.get("test_diff_stat"), len(commits))
    return redact("\n".join(lines) + "\n\n")
