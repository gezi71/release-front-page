#!/usr/bin/env python3
"""Collect deterministic, evidence-backed release data from a local Git range."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
CATEGORY_ORDER = [
    "Highlights",
    "Features",
    "Fixes",
    "Performance",
    "Developer Experience",
    "Documentation",
    "Breaking Changes",
    "Migration",
    "Other",
]
TYPE_TO_CATEGORY = {
    "feat": "Features",
    "feature": "Features",
    "fix": "Fixes",
    "perf": "Performance",
    "build": "Developer Experience",
    "chore": "Developer Experience",
    "ci": "Developer Experience",
    "refactor": "Developer Experience",
    "style": "Developer Experience",
    "test": "Developer Experience",
    "docs": "Documentation",
    "doc": "Documentation",
    "highlight": "Highlights",
    "migration": "Migration",
}
CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[A-Za-z][A-Za-z0-9-]*)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<title>.+)$"
)
BREAKING_RE = re.compile(r"^BREAKING[ -]CHANGE:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
PR_RE = re.compile(r"(?:\(|\s)#(?P<number>[1-9][0-9]*)(?:\)|\s|$)")
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
UNSAFE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
IDENTITY_TRAILER_RE = re.compile(
    r"^(?:co-authored-by|signed-off-by|reviewed-by|acked-by|tested-by|reported-by|helped-by|suggested-by|mentored-by):",
    re.IGNORECASE,
)
GITHUB_PR_RE = re.compile(
    r"^https://github\.com/(?P<slug>[^/\s]+/[^/\s]+)/pull/(?P<number>[1-9][0-9]*)$"
)


class CollectionError(RuntimeError):
    """Expected input or Git error."""


def run_command(command: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise CollectionError(f"could not run {command[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise CollectionError(f"{command[0]} failed: {detail}")
    return result.stdout


def git(repo: Path, *args: str) -> str:
    return run_command(["git", *args], repo)


def validate_repository(repo: Path) -> Path:
    if not repo.exists() or not repo.is_dir():
        raise CollectionError(f"repository directory does not exist: {repo}")
    if shutil.which("git") is None:
        raise CollectionError("git is not installed or not on PATH")
    try:
        inside = git(repo, "rev-parse", "--is-inside-work-tree").strip()
    except CollectionError as exc:
        raise CollectionError(f"not a Git work tree: {repo}") from exc
    if inside != "true":
        raise CollectionError(f"not a Git work tree: {repo}")
    return Path(git(repo, "rev-parse", "--show-toplevel").strip())


def resolve_ref(repo: Path, ref: str) -> str:
    if not ref.strip():
        raise CollectionError("Git refs must not be empty")
    try:
        return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    except CollectionError as exc:
        raise CollectionError(f"invalid Git ref {ref!r}") from exc


def parse_subject(subject: str, body: str) -> dict[str, Any]:
    conventional = CONVENTIONAL_RE.match(subject.strip())
    commit_type = "other"
    scope = None
    title = subject.strip()
    bang = False
    if conventional:
        commit_type = conventional.group("type").lower()
        scope = conventional.group("scope")
        bang = bool(conventional.group("bang"))
        title = conventional.group("title").strip()

    breaking_match = BREAKING_RE.search(body)
    breaking = bang or bool(breaking_match)
    migration_note = breaking_match.group(1).strip() if breaking_match else None
    is_revert = subject.lower().startswith("revert") or commit_type == "revert"

    if breaking:
        category = "Breaking Changes"
    elif is_revert:
        category = "Other"
    else:
        category = TYPE_TO_CATEGORY.get(commit_type, "Other")

    return {
        "type": commit_type,
        "scope": scope,
        "title": title,
        "breaking": breaking,
        "migration_note": migration_note,
        "revert": is_revert,
        "category": category,
    }


def redact_identity_text(value: str) -> str:
    """Remove identity trailers and redact email-shaped text from commit prose."""
    kept: list[str] = []
    normalized = UNSAFE_CONTROL_RE.sub("�", value).replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        if IDENTITY_TRAILER_RE.match(line.strip()):
            continue
        kept.append(EMAIL_RE.sub("[redacted-email]", line))
    return "\n".join(kept).rstrip()


def read_commit_records(
    repo: Path, from_sha: str, to_sha: str, include_merges: bool
) -> list[tuple[str, str, str, list[str], str]]:
    """Read SHA, subject, body, parents, and author in one Git process."""
    command = ["log", "--reverse", "--format=%H%x00%s%x00%b%x00%P%x00%aN%x00"]
    if not include_merges:
        command.append("--no-merges")
    command.append(f"{from_sha}..{to_sha}")
    output = git(repo, *command)
    fields = output.split("\x00")
    if fields and not fields[-1].strip("\n"):
        fields.pop()
    if len(fields) % 5:
        raise CollectionError("could not parse batched commit metadata")
    records: list[tuple[str, str, str, list[str], str]] = []
    for offset in range(0, len(fields), 5):
        sha, subject, body, parents_raw, author = fields[offset : offset + 5]
        sha = sha.strip("\n")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise CollectionError("could not parse batched commit SHA")
        records.append((sha, subject, body.rstrip(), parents_raw.split(), author.strip()))
    return records


def parse_numstat(output: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    records = output.split("\x00") if "\x00" in output else output.splitlines()
    for record in records:
        if not record:
            continue
        pieces = record.split("\t", 2)
        if len(pieces) != 3:
            continue
        added_raw, deleted_raw, path = pieces
        binary = added_raw == "-" or deleted_raw == "-"
        files.append(
            {
                "path": path,
                "additions": None if binary else int(added_raw),
                "deletions": None if binary else int(deleted_raw),
                "binary": binary,
            }
        )
    return sorted(files, key=lambda item: item["path"])


def read_file_stats(repo: Path, sha: str, parents: list[str]) -> list[dict[str, Any]]:
    if parents:
        output = git(repo, "diff", "--numstat", "-z", "--no-renames", parents[0], sha)
    else:
        output = git(repo, "diff-tree", "--root", "--no-commit-id", "--numstat", "-z", "-r", "--no-renames", sha)
    return parse_numstat(output)


def read_range_stats(repo: Path, from_sha: str, to_sha: str) -> list[dict[str, Any]]:
    """Return the net file change between refs, without double-counting commit churn."""
    return parse_numstat(git(repo, "diff", "--numstat", "-z", "--no-renames", from_sha, to_sha))


def repository_slug(repo: Path) -> str | None:
    try:
        remote = git(repo, "remote", "get-url", "origin").strip()
    except CollectionError:
        return None
    patterns = [
        r"github\.com[:/](?P<slug>[^/\s]+/[^/\s]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, remote)
        if match:
            return match.group("slug")
    return None


def load_pr(repo: Path, slug: str, number: int) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = run_command(
            ["gh", "pr", "view", str(number), "--repo", slug, "--json", "number,title,url,labels"],
            repo,
        )
        data = json.loads(raw)
    except (CollectionError, json.JSONDecodeError) as exc:
        return None, str(exc)
    returned_number = data.get("number")
    if not isinstance(returned_number, int) or isinstance(returned_number, bool):
        return None, "gh returned an invalid PR number"
    raw_labels = data.get("labels", [])
    if not isinstance(raw_labels, list):
        return None, "gh returned invalid PR labels"
    labels = sorted(
        redact_identity_text(str(label.get("name", "")))
        for label in raw_labels
        if isinstance(label, dict) and label.get("name")
    )
    url = str(data.get("url", ""))
    match = GITHUB_PR_RE.fullmatch(url)
    if (
        returned_number != number
        or not match
        or match.group("slug").casefold() != slug.casefold()
        or int(match.group("number")) != number
    ):
        return None, "gh returned a PR URL outside the requested GitHub repository"
    return {
        "number": returned_number,
        "title": redact_identity_text(str(data["title"])),
        "url": url,
        "labels": labels,
    }, None


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def validate_output_path(repo: Path, output: Path) -> Path:
    output = output.expanduser()
    if output.is_symlink():
        raise CollectionError("output must not be a symbolic link")
    output = output.resolve(strict=False)
    git_dir = (repo / ".git").resolve(strict=False)
    if output == git_dir or git_dir in output.parents:
        raise CollectionError("output must not be written inside .git")
    try:
        relative = output.relative_to(repo)
    except ValueError:
        return output
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative.as_posix()],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if tracked.returncode == 0:
        raise CollectionError(f"output would overwrite a tracked repository file: {relative.as_posix()}")
    return output


def validate_gh(repo: Path) -> tuple[str | None, str | None]:
    if shutil.which("gh") is None:
        return None, "gh is not installed"
    try:
        run_command(["gh", "auth", "status"], repo)
    except CollectionError as exc:
        return None, str(exc)
    slug = repository_slug(repo)
    if not slug:
        return None, "origin is not a recognizable GitHub repository"
    return slug, None


def collect(args: argparse.Namespace) -> dict[str, Any]:
    repo = validate_repository(Path(args.repo).expanduser())
    from_sha = resolve_ref(repo, args.from_ref)
    to_sha = resolve_ref(repo, args.to_ref)
    records = read_commit_records(repo, from_sha, to_sha, bool(args.include_merges))

    remote_slug = repository_slug(repo)
    gh_slug = None
    gh_failure = None
    if args.use_gh:
        gh_slug, gh_failure = validate_gh(repo)
    enrichment: dict[str, Any] = {
        "requested": bool(args.use_gh),
        "attempted": 0,
        "succeeded": 0,
        "failures": [],
        "failure_reason": gh_failure,
    }
    commits: list[dict[str, Any]] = []
    contributor_counts: Counter[str] = Counter()
    for sha, raw_subject, raw_body, parents, raw_author in records:
        parsed = parse_subject(raw_subject, raw_body)
        subject = redact_identity_text(raw_subject)
        body = redact_identity_text(raw_body)
        files = read_file_stats(repo, sha, parents)
        pr = None
        pr_match = PR_RE.search(raw_subject)
        if gh_slug and pr_match:
            number = int(pr_match.group("number"))
            enrichment["attempted"] += 1
            pr, failure = load_pr(repo, gh_slug, number)
            if pr is None:
                enrichment["failures"].append({"number": number, "reason": failure or "lookup failed"})
            else:
                enrichment["succeeded"] += 1
        commit: dict[str, Any] = {
            "sha": sha,
            "short_sha": sha[:7],
            "subject": subject,
            "body": body,
            "type": parsed["type"],
            "scope": redact_identity_text(parsed["scope"]) if parsed["scope"] else None,
            "category": parsed["category"],
            "breaking": parsed["breaking"],
            "migration_note": (
                redact_identity_text(parsed["migration_note"]) if parsed["migration_note"] else None
            ),
            "revert": parsed["revert"],
            "merge": len(parents) > 1,
            "highlight": False,
            "parents": parents,
            "files": files,
            "stats": {
                "files_changed": len(files),
                "additions": sum(item["additions"] or 0 for item in files),
                "deletions": sum(item["deletions"] or 0 for item in files),
                "binary_files": sum(1 for item in files if item["binary"]),
            },
            "provenance": {"commit": sha, "pull_request": pr},
            "summaries": {"en": subject, "zh-CN": subject},
            "confidence": "medium",
        }
        if args.include_contributors:
            author = redact_identity_text(raw_author).replace("\n", " ").strip()
            if author:
                contributor_counts[author] += 1
        commits.append(commit)

    range_files = read_range_stats(repo, from_sha, to_sha)
    category_counts = Counter(commit["category"] for commit in commits)
    summary = {
        "change_basis": "net_ref_diff",
        "commit_count": len(commits),
        "merge_count": sum(1 for commit in commits if commit["merge"]),
        "breaking_count": sum(1 for commit in commits if commit["breaking"]),
        "revert_count": sum(1 for commit in commits if commit["revert"]),
        "files_changed": len(range_files),
        "additions": sum(item["additions"] or 0 for item in range_files),
        "deletions": sum(item["deletions"] or 0 for item in range_files),
        "categories": {category: category_counts.get(category, 0) for category in CATEGORY_ORDER},
    }
    contributors = [
        {"name": name, "commits": count}
        for name, count in sorted(contributor_counts.items(), key=lambda pair: (-pair[1], pair[0].casefold()))
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "version": args.version,
        "repository": {"name": repo.name, "remote_slug": remote_slug},
        "range": {
            "from": args.from_ref,
            "to": args.to_ref,
            "from_sha": from_sha,
            "to_sha": to_sha,
            "include_merges": bool(args.include_merges),
        },
        "github_enrichment": enrichment,
        "editorial": {
            "en": {
                "headline": f"{args.version}: the evidence-backed edition",
                "dek": f"A draft assembled from {len(commits)} commits between {args.from_ref} and {args.to_ref}.",
            },
            "zh-CN": {
                "headline": f"{args.version}：有据可查的发布专刊",
                "dek": f"基于 {args.from_ref} 至 {args.to_ref} 之间的 {len(commits)} 个提交生成的草稿。",
            },
        },
        "category_order": CATEGORY_ORDER,
        "summary": summary,
        "contributors": contributors,
        "commits": commits,
        "limitations": [
            "Commit messages and diffs provide evidence, not proof of user impact.",
            "Generated summaries remain drafts until a maintainer reviews them.",
            "Email-shaped text and identity trailers are removed from collected commit prose.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to a local Git repository")
    parser.add_argument("--from", dest="from_ref", required=True, help="Starting Git ref (exclusive)")
    parser.add_argument("--to", dest="to_ref", required=True, help="Ending Git ref (inclusive)")
    parser.add_argument("--version", required=True, help="Version label for the release")
    parser.add_argument("--output", required=True, help="Path for release-data.json")
    parser.add_argument("--include-merges", action="store_true", help="Include merge commits")
    parser.add_argument("--include-contributors", action="store_true", help="Include public author names, never emails")
    parser.add_argument("--use-gh", action="store_true", help="Explicitly allow authenticated gh PR metadata lookup")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        repo = validate_repository(Path(args.repo).expanduser())
        output = validate_output_path(repo, Path(args.output))
        data = collect(args)
        atomic_write_text(output, json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    except CollectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: could not write release data: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
