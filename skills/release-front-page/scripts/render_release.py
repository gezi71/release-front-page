#!/usr/bin/env python3
"""Render deterministic release notes and self-contained release visuals."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape


LOCALES = {
    "en": {
        "release_notes": "Release notes draft",
        "evidence": "Evidence",
        "commits": "commits",
        "files": "files changed",
        "lines": "lines changed",
        "highlights": "Highlights",
        "empty": "No commits were found in this range.",
        "draft": "Draft: verify user impact and migration advice before publishing.",
        "provenance": "Provenance",
        "migration": "Migration notes",
        "limitations": "Limitations",
        "release": "Release",
        "commits_short": "COMMITS",
        "files_short": "FILES",
        "social_draft": "EVIDENCE-BACKED DRAFT · VERIFY BEFORE PUBLISHING",
        "social_evidence": "EVIDENCE",
        "breaking": "BREAKING",
        "poster_scope": "Poster shows {shown} of {total} commits; full notes contain every change.",
        "html_scope": "Page shows {shown} of {total} commits; Markdown and JSON retain every change.",
        "more": "+{count} more",
    },
    "zh-CN": {
        "release_notes": "发布说明草稿",
        "evidence": "证据",
        "commits": "个提交",
        "files": "个文件变更",
        "lines": "行变更",
        "highlights": "亮点",
        "empty": "该范围内没有提交。",
        "draft": "草稿：发布前请人工核对用户影响与迁移建议。",
        "provenance": "证据来源",
        "migration": "迁移说明",
        "limitations": "限制",
        "release": "发布",
        "commits_short": "提交",
        "files_short": "文件",
        "social_draft": "证据驱动草稿 · 发布前请人工核对",
        "social_evidence": "证据",
        "breaking": "破坏性变更",
        "poster_scope": "头版展示 {shown}/{total} 个提交；完整说明包含全部变更。",
        "html_scope": "页面展示 {shown}/{total} 个提交；Markdown 与 JSON 保留全部变更。",
        "more": "另有 {count} 项",
    },
}

CATEGORY_LABELS = {
    "en": {
        "Highlights": "Highlights",
        "Features": "Features",
        "Fixes": "Fixes",
        "Performance": "Performance",
        "Developer Experience": "Developer Experience",
        "Documentation": "Documentation",
        "Breaking Changes": "Breaking Changes",
        "Migration": "Migration",
        "Other": "Other",
    },
    "zh-CN": {
        "Highlights": "亮点",
        "Features": "新功能",
        "Fixes": "修复",
        "Performance": "性能",
        "Developer Experience": "开发者体验",
        "Documentation": "文档",
        "Breaking Changes": "破坏性变更",
        "Migration": "迁移",
        "Other": "其他",
    },
}

THEMES = {
    "broadsheet": {
        "paper": "#f4eddf",
        "ink": "#171511",
        "muted": "#6d675d",
        "accent": "#a32921",
        "panel": "#e7ddcb",
    },
    "modern": {
        "paper": "#101418",
        "ink": "#f2f4ee",
        "muted": "#aab4b9",
        "accent": "#63d6c5",
        "panel": "#1b242a",
    },
}


class RenderError(RuntimeError):
    """Invalid input or output error."""


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SLUG_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
MARKDOWN_SPECIAL_RE = re.compile(r"([\\`*_{}\[\]<>#+.!|()-])")


def markdown_text(value: Any) -> str:
    flattened = " ".join(str(value).replace("\r", "\n").splitlines())
    return MARKDOWN_SPECIAL_RE.sub(r"\\\1", flattened)


def valid_pr(pr: Any, remote_slug: str | None) -> bool:
    if (
        not isinstance(pr, dict)
        or not isinstance(pr.get("number"), int)
        or isinstance(pr.get("number"), bool)
        or pr["number"] < 1
    ):
        return False
    if not remote_slug or not SLUG_RE.fullmatch(remote_slug):
        return False
    expected = f"https://github.com/{remote_slug}/pull/{pr['number']}"
    return pr.get("url") == expected


def require_nonnegative_int(mapping: dict[str, Any], key: str, label: str) -> None:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RenderError(f"{label}.{key} must be a non-negative integer")


def require_string(mapping: dict[str, Any], key: str, label: str, *, allow_empty: bool = False) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise RenderError(f"{label}.{key} must be {qualifier}")
    return value


def validate_commit(commit: Any, index: int, remote_slug: str | None) -> None:
    label = f"commits[{index}]"
    if not isinstance(commit, dict):
        raise RenderError(f"{label} must be an object")
    sha = commit.get("sha")
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise RenderError(f"{label}.sha must be a 40-character lowercase Git SHA")
    if commit.get("short_sha") != sha[:7]:
        raise RenderError(f"{label}.short_sha must match sha")
    provenance = commit.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("commit") != sha:
        raise RenderError(f"{label}.provenance.commit must match sha")
    pr = provenance.get("pull_request")
    if pr is not None and not valid_pr(pr, remote_slug):
        raise RenderError(f"{label}.provenance.pull_request must be a matching GitHub PR URL")
    if pr is not None:
        require_string(pr, "title", f"{label}.provenance.pull_request")
        labels = pr.get("labels")
        if not isinstance(labels, list) or any(not isinstance(item, str) or not item.strip() for item in labels):
            raise RenderError(f"{label}.provenance.pull_request.labels must be a list of strings")
    for key in ("subject", "type", "category", "confidence"):
        require_string(commit, key, label)
    require_string(commit, "body", label, allow_empty=True)
    if commit["confidence"] not in {"low", "medium", "high"}:
        raise RenderError(f"{label}.confidence must be low, medium, or high")
    for key in ("scope", "migration_note"):
        if commit.get(key) is not None and not isinstance(commit[key], str):
            raise RenderError(f"{label}.{key} must be a string or null")
    for key in ("breaking", "revert", "merge", "highlight"):
        if not isinstance(commit.get(key), bool):
            raise RenderError(f"{label}.{key} must be boolean")
    stats = commit.get("stats")
    if not isinstance(stats, dict):
        raise RenderError(f"{label}.stats must be an object")
    for key in ("files_changed", "additions", "deletions", "binary_files"):
        require_nonnegative_int(stats, key, f"{label}.stats")
    parents = commit.get("parents")
    if not isinstance(parents, list) or any(not isinstance(parent, str) or not SHA_RE.fullmatch(parent) for parent in parents):
        raise RenderError(f"{label}.parents must contain only full Git SHAs")
    files = commit.get("files")
    if not isinstance(files, list):
        raise RenderError(f"{label}.files must be a list")
    for file_index, file_data in enumerate(files):
        file_label = f"{label}.files[{file_index}]"
        if not isinstance(file_data, dict):
            raise RenderError(f"{file_label} must be an object")
        require_string(file_data, "path", file_label)
        if not isinstance(file_data.get("binary"), bool):
            raise RenderError(f"{file_label}.binary must be boolean")
        for key in ("additions", "deletions"):
            value = file_data.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise RenderError(f"{file_label}.{key} must be a non-negative integer or null")
        has_null_stats = file_data.get("additions") is None and file_data.get("deletions") is None
        has_partial_null = (file_data.get("additions") is None) != (file_data.get("deletions") is None)
        if has_partial_null or file_data["binary"] != has_null_stats:
            raise RenderError(f"{file_label}.binary must match null line statistics")
    expected_stats = {
        "files_changed": len(files),
        "additions": sum(item.get("additions") or 0 for item in files),
        "deletions": sum(item.get("deletions") or 0 for item in files),
        "binary_files": sum(1 for item in files if item["binary"]),
    }
    if any(stats[key] != value for key, value in expected_stats.items()):
        raise RenderError(f"{label}.stats must match files")
    summaries = commit.get("summaries")
    if not isinstance(summaries, dict):
        raise RenderError(f"{label}.summaries must be an object")
    for locale in LOCALES:
        require_string(summaries, locale, f"{label}.summaries")


def load_data(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderError(f"could not read input JSON: {exc}") from exc
    required = {
        "schema_version",
        "version",
        "repository",
        "range",
        "summary",
        "commits",
        "contributors",
        "category_order",
        "editorial",
        "github_enrichment",
        "limitations",
    }
    missing = sorted(required - data.keys())
    if missing:
        raise RenderError(f"input is missing required keys: {', '.join(missing)}")
    if data.get("schema_version") != "1.0":
        raise RenderError("unsupported schema_version; expected 1.0")
    if not isinstance(data.get("version"), str) or not data["version"].strip():
        raise RenderError("version must be a non-empty string")
    repository = data.get("repository")
    if not isinstance(repository, dict):
        raise RenderError("repository must be an object")
    require_string(repository, "name", "repository")
    remote_slug = repository.get("remote_slug")
    if remote_slug is not None and (not isinstance(remote_slug, str) or not SLUG_RE.fullmatch(remote_slug)):
        raise RenderError("repository.remote_slug must be owner/repository or null")
    if not isinstance(data["commits"], list):
        raise RenderError("commits must be a list")
    range_data = data.get("range")
    if not isinstance(range_data, dict):
        raise RenderError("range must be an object")
    for key in ("from", "to"):
        require_string(range_data, key, "range")
    for key in ("from_sha", "to_sha"):
        value = require_string(range_data, key, "range")
        if not SHA_RE.fullmatch(value):
            raise RenderError(f"range.{key} must be a full Git SHA")
    if not isinstance(range_data.get("include_merges"), bool):
        raise RenderError("range.include_merges must be boolean")
    order = data.get("category_order")
    if (
        not isinstance(order, list)
        or not order
        or any(not isinstance(item, str) or not item.strip() for item in order)
        or len(set(order)) != len(order)
    ):
        raise RenderError("category_order must be a non-empty list of unique strings")
    editorial = data.get("editorial")
    if not isinstance(editorial, dict):
        raise RenderError("editorial must be an object")
    for locale in LOCALES:
        locale_data = editorial.get(locale)
        if not isinstance(locale_data, dict):
            raise RenderError(f"editorial.{locale} must be an object")
        require_string(locale_data, "headline", f"editorial.{locale}")
        require_string(locale_data, "dek", f"editorial.{locale}")
    summary = data.get("summary")
    if not isinstance(summary, dict):
        raise RenderError("summary must be an object")
    for key in (
        "commit_count",
        "merge_count",
        "breaking_count",
        "revert_count",
        "files_changed",
        "additions",
        "deletions",
    ):
        require_nonnegative_int(summary, key, "summary")
    if summary["commit_count"] != len(data["commits"]):
        raise RenderError("summary.commit_count must match commits length")
    if summary.get("change_basis") != "net_ref_diff":
        raise RenderError("summary.change_basis must be net_ref_diff")
    categories = summary.get("categories")
    if not isinstance(categories, dict):
        raise RenderError("summary.categories must be an object")
    for category in order:
        require_nonnegative_int(categories, category, "summary.categories")
    contributors = data.get("contributors")
    if not isinstance(contributors, list):
        raise RenderError("contributors must be a list")
    for index, contributor in enumerate(contributors):
        if not isinstance(contributor, dict):
            raise RenderError(f"contributors[{index}] must be an object")
        require_string(contributor, "name", f"contributors[{index}]")
        require_nonnegative_int(contributor, "commits", f"contributors[{index}]")
    enrichment = data.get("github_enrichment")
    if not isinstance(enrichment, dict) or not isinstance(enrichment.get("requested"), bool):
        raise RenderError("github_enrichment.requested must be boolean")
    for key in ("attempted", "succeeded"):
        require_nonnegative_int(enrichment, key, "github_enrichment")
    failures = enrichment.get("failures")
    if not isinstance(failures, list):
        raise RenderError("github_enrichment.failures must be a list")
    for index, failure in enumerate(failures):
        if not isinstance(failure, dict):
            raise RenderError(f"github_enrichment.failures[{index}] must be an object")
        number = failure.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise RenderError(f"github_enrichment.failures[{index}].number must be a positive integer")
        require_string(failure, "reason", f"github_enrichment.failures[{index}]")
    if enrichment["succeeded"] + len(failures) != enrichment["attempted"]:
        raise RenderError("github_enrichment counts are inconsistent")
    if "failure_reason" not in enrichment:
        raise RenderError("github_enrichment.failure_reason is required")
    failure_reason = enrichment.get("failure_reason")
    if failure_reason is not None and (not isinstance(failure_reason, str) or not failure_reason.strip()):
        raise RenderError("github_enrichment.failure_reason must be a non-empty string or null")
    if not enrichment["requested"] and failure_reason is not None:
        raise RenderError("github_enrichment.failure_reason requires requested=true")
    if not enrichment["requested"] and (enrichment["attempted"] or enrichment["succeeded"] or failures):
        raise RenderError("github_enrichment lookups require requested=true")
    if failure_reason is not None and enrichment["attempted"]:
        raise RenderError("github_enrichment cannot attempt lookups after setup failure")
    limitations = data.get("limitations")
    if not isinstance(limitations, list) or any(not isinstance(item, str) or not item.strip() for item in limitations):
        raise RenderError("limitations must be a list of non-empty strings")
    for index, commit in enumerate(data["commits"]):
        validate_commit(commit, index, remote_slug)
    expected_counts = {
        "merge_count": sum(1 for commit in data["commits"] if commit["merge"]),
        "breaking_count": sum(1 for commit in data["commits"] if commit["breaking"]),
        "revert_count": sum(1 for commit in data["commits"] if commit["revert"]),
    }
    for key, expected in expected_counts.items():
        if summary[key] != expected:
            raise RenderError(f"summary.{key} must match commits")
    unknown_categories = sorted({commit["category"] for commit in data["commits"]} - set(order))
    if unknown_categories:
        raise RenderError(f"commit categories are missing from category_order: {', '.join(unknown_categories)}")
    for category in order:
        expected = sum(1 for commit in data["commits"] if commit["category"] == category)
        if categories[category] != expected:
            raise RenderError(f"summary.categories.{category} must match commits")
    return data


def locale_text(data: dict[str, Any], locale: str) -> tuple[str, str]:
    editorial = data.get("editorial", {}).get(locale, {})
    fallback = data.get("editorial", {}).get("en", {})
    headline = editorial.get("headline") or fallback.get("headline") or f"{data['version']} release"
    dek = editorial.get("dek") or fallback.get("dek") or LOCALES[locale]["draft"]
    return str(headline), str(dek)


def summary_for(commit: dict[str, Any], locale: str) -> str:
    summaries = commit.get("summaries", {})
    return str(summaries.get(locale) or summaries.get("en") or commit.get("subject") or "Untitled change")


def provenance_for(commit: dict[str, Any], markdown: bool = False, remote_slug: str | None = None) -> str:
    provenance = commit.get("provenance", {})
    sha = str(provenance.get("commit") or commit.get("sha") or "")[:7]
    pr = provenance.get("pull_request")
    if pr and valid_pr(pr, remote_slug):
        if markdown:
            return f"`{sha}` · [#{pr['number']}]({pr['url']})"
        return f"{sha} · PR #{pr['number']}"
    return f"`{sha}`" if markdown else sha


def grouped_commits(data: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    order = data.get("category_order") or [
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
    commits = data["commits"]
    groups = []
    for category in order:
        matches = [commit for commit in commits if commit.get("category", "Other") == category]
        if matches:
            groups.append((category, matches))
    unknown = sorted({commit.get("category", "Other") for commit in commits} - set(order))
    for category in unknown:
        groups.append((category, [commit for commit in commits if commit.get("category") == category]))
    return groups


def select_highlights(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [commit for commit in data["commits"] if commit.get("highlight")][:3]


def render_markdown(data: dict[str, Any], locale: str) -> str:
    labels = LOCALES[locale]
    category_labels = CATEGORY_LABELS[locale]
    headline, dek = locale_text(data, locale)
    summary = data["summary"]
    lines = [
        f"# {markdown_text(headline)}",
        "",
        f"> {markdown_text(dek)}",
        "",
        f"**{labels['evidence']}:** {summary['commit_count']} {labels['commits']} · "
        f"{summary['files_changed']} {labels['files']} · "
        f"+{summary['additions']} / -{summary['deletions']}",
        "",
        f"> {labels['draft']}",
        "",
    ]
    highlights = select_highlights(data)
    if highlights:
        lines.extend([f"## {labels['highlights']}", ""])
        for commit in highlights:
            lines.append(
                f"- {markdown_text(summary_for(commit, locale))} — "
                f"{provenance_for(commit, markdown=True, remote_slug=data['repository'].get('remote_slug'))}"
            )
        lines.append("")
    if not data["commits"]:
        lines.extend([labels["empty"], ""])
    for category, commits in grouped_commits(data):
        lines.extend([f"## {markdown_text(category_labels.get(category, category))}", ""])
        for commit in commits:
            breaking = f" **{labels['breaking']}**" if commit.get("breaking") else ""
            lines.append(
                f"- {markdown_text(summary_for(commit, locale))}{breaking} — "
                f"{provenance_for(commit, markdown=True, remote_slug=data['repository'].get('remote_slug'))}"
            )
            if commit.get("migration_note"):
                lines.append(f"  - {labels['migration']}: {markdown_text(commit['migration_note'])}")
        lines.append("")
    limitations = data.get("limitations", [])
    if limitations:
        lines.extend([f"## {labels['limitations']}", ""])
        lines.extend(f"- {markdown_text(item)}" for item in limitations)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(data: dict[str, Any], locale: str, theme: str) -> str:
    palette = THEMES[theme]
    labels = LOCALES[locale]
    category_labels = CATEGORY_LABELS[locale]
    headline, dek = locale_text(data, locale)
    summary = data["summary"]
    sections = []
    shown_commits = 0
    for category, commits in grouped_commits(data):
        items = []
        visible_commits = commits[:12]
        for commit in visible_commits:
            badge = f'<span class="breaking">{html.escape(labels["breaking"])}</span>' if commit.get("breaking") else ""
            items.append(
                f'<li><span>{html.escape(summary_for(commit, locale))}{badge}</span>'
                f'<code>{html.escape(provenance_for(commit, remote_slug=data["repository"].get("remote_slug")))}</code></li>'
            )
        shown_commits += len(visible_commits)
        hidden = len(commits) - len(visible_commits)
        if hidden:
            items.append(f'<li class="more">{html.escape(labels["more"].format(count=hidden))}</li>')
        sections.append(
            f'<section><h2>{html.escape(category_labels.get(category, category))}</h2><ul>{"".join(items)}</ul></section>'
        )
    empty = f'<p class="empty">{html.escape(labels["empty"])}</p>' if not data["commits"] else ""
    return f"""<!doctype html>
<html lang="{html.escape(locale)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(headline)}</title>
<style>
:root{{--paper:{palette['paper']};--ink:{palette['ink']};--muted:{palette['muted']};--accent:{palette['accent']};--panel:{palette['panel']}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Georgia,"Times New Roman",serif}}
main{{width:min(1120px,92vw);margin:0 auto;padding:38px 0 72px}}header{{text-align:center;border-block:5px double var(--ink);padding:22px 4vw;margin-bottom:26px}}
.kicker{{font:700 12px/1.2 ui-monospace,monospace;letter-spacing:.18em;text-transform:uppercase;color:var(--accent)}}h1{{font-size:clamp(42px,8vw,94px);line-height:.88;margin:18px 0;letter-spacing:-.055em}}.dek{{font-size:clamp(18px,2.5vw,28px);color:var(--muted);max-width:760px;margin:auto}}
.facts{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--ink);border:1px solid var(--ink);margin:26px 0}}.fact{{background:var(--panel);padding:18px;text-align:center}}.fact strong{{display:block;font-size:34px}}.fact span{{font:700 11px/1.2 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.1em}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px 34px}}section{{min-width:0;border-top:3px solid var(--ink);margin-bottom:30px}}h2{{font-size:25px;text-transform:uppercase;letter-spacing:.04em;margin:8px 0}}ul{{list-style:none;padding:0;margin:0}}li{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;padding:12px 0;border-top:1px solid color-mix(in srgb,var(--ink) 22%,transparent);line-height:1.35}}code{{color:var(--muted);white-space:nowrap}}.breaking{{display:inline-block;font:700 10px/1 ui-monospace,monospace;color:var(--paper);background:var(--accent);padding:4px 6px;margin-left:8px}}footer{{border-top:5px double var(--ink);margin-top:30px;padding-top:18px;color:var(--muted)}}
@media(max-width:650px){{.facts,.grid{{grid-template-columns:1fr}}li{{grid-template-columns:1fr}}}}@media print{{main{{width:100%;padding:0}}}}
</style>
</head>
<body><main>
<header><div class="kicker">{html.escape(data['repository']['name'])} · {html.escape(data['version'])}</div><h1>{html.escape(headline)}</h1><p class="dek">{html.escape(dek)}</p></header>
<div class="facts"><div class="fact"><strong>{summary['commit_count']}</strong><span>{html.escape(labels['commits'])}</span></div><div class="fact"><strong>{summary['files_changed']}</strong><span>{html.escape(labels['files'])}</span></div><div class="fact"><strong>+{summary['additions']} / -{summary['deletions']}</strong><span>{html.escape(labels['lines'])}</span></div></div>
{empty}<div class="grid">{"".join(sections)}</div>
<footer>{html.escape(labels['html_scope'].format(shown=shown_commits, total=len(data['commits'])))}<br>{html.escape(labels['draft'])}</footer>
</main></body></html>
"""


def ellipsize(text: str, max_chars: int) -> str:
    value = str(text)
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def svg_text_lines(text: str, width: int, max_lines: int | None = None) -> list[str]:
    lines = textwrap.wrap(str(text), width=width, break_long_words=True, break_on_hyphens=False) or [""]
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = ellipsize(lines[-1], max(2, width - 1))
    return lines


def render_front_page_svg(data: dict[str, Any], locale: str, theme: str) -> str:
    palette = THEMES[theme]
    labels = LOCALES[locale]
    category_labels = CATEGORY_LABELS[locale]
    headline, dek = locale_text(data, locale)
    summary = data["summary"]
    headline_lines = svg_text_lines(headline, 28, 2)
    dek_lines = svg_text_lines(dek, 74, 2)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1000" role="img" aria-labelledby="title desc">',
        f'<title id="title">{xml_escape(headline)}</title>',
        f'<desc id="desc">{xml_escape(dek)}</desc>',
        f'<rect width="1600" height="1000" fill="{palette["paper"]}"/>',
        f'<style>text{{fill:{palette["ink"]};font-family:Georgia,serif}}.mono{{font-family:ui-monospace,monospace}}.muted{{fill:{palette["muted"]}}}.accent{{fill:{palette["accent"]}}}</style>',
        f'<text x="800" y="64" text-anchor="middle" class="mono accent" font-size="20" font-weight="700" letter-spacing="5">{xml_escape(ellipsize(data["repository"]["name"].upper(), 42))} / {xml_escape(ellipsize(data["version"].upper(), 42))}</text>',
        f'<path d="M80 90H1520M80 102H1520" stroke="{palette["ink"]}" stroke-width="4"/>',
    ]
    y = 190
    for line in headline_lines:
        parts.append(f'<text x="800" y="{y}" text-anchor="middle" font-size="86" font-weight="700" letter-spacing="-3">{xml_escape(line)}</text>')
        y += 82
    y += 12
    for line in dek_lines:
        parts.append(f'<text x="800" y="{y}" text-anchor="middle" class="muted" font-size="25">{xml_escape(line)}</text>')
        y += 34
    facts_y = max(410, y + 22)
    parts.extend(
        [
            f'<rect x="80" y="{facts_y}" width="1440" height="112" fill="{palette["panel"]}" stroke="{palette["ink"]}"/>',
            f'<path d="M560 {facts_y}V{facts_y + 112}M1040 {facts_y}V{facts_y + 112}" stroke="{palette["ink"]}"/>',
        ]
    )
    facts = [
        (summary["commit_count"], labels["commits"]),
        (summary["files_changed"], labels["files"]),
        (f'+{summary["additions"]} / -{summary["deletions"]}', labels["lines"]),
    ]
    for index, (value, label) in enumerate(facts):
        x = 320 + index * 480
        parts.append(f'<text x="{x}" y="{facts_y + 49}" text-anchor="middle" font-size="38" font-weight="700">{xml_escape(str(value))}</text>')
        parts.append(f'<text x="{x}" y="{facts_y + 82}" text-anchor="middle" class="mono muted" font-size="15" letter-spacing="2">{xml_escape(label.upper())}</text>')

    columns = [(80, 760), (840, 760)]
    groups = grouped_commits(data)
    shown_commits = 0
    for column_index, (x, width) in enumerate(columns):
        column_groups = groups[column_index::2]
        group_y = facts_y + 158
        for category, commits in column_groups:
            if group_y > 910:
                break
            label = category_labels.get(category, category).upper()
            parts.append(f'<path d="M{x} {group_y}H{x + width - 80}" stroke="{palette["ink"]}" stroke-width="4"/>')
            parts.append(f'<text x="{x}" y="{group_y + 32}" font-size="26" font-weight="700" letter-spacing="2">{xml_escape(label)}</text>')
            group_y += 62
            visible_commits = commits[:3]
            for commit in visible_commits:
                lines = svg_text_lines(summary_for(commit, locale), 48)[:2]
                for line in lines:
                    parts.append(f'<text x="{x}" y="{group_y}" font-size="19">{xml_escape(line)}</text>')
                    group_y += 25
                parts.append(
                    f'<text x="{x + width - 85}" y="{group_y - 25}" text-anchor="end" class="mono muted" font-size="14">'
                    f'{xml_escape(provenance_for(commit, remote_slug=data["repository"].get("remote_slug")))}</text>'
                )
                group_y += 14
                shown_commits += 1
            hidden = len(commits) - len(visible_commits)
            if hidden:
                more = labels["more"].format(count=hidden)
                parts.append(
                    f'<text x="{x}" y="{group_y + 8}" class="mono muted" font-size="14">'
                    f'{xml_escape(more)}</text>'
                )
                group_y += 18
            group_y += 14
    scope = labels["poster_scope"].format(shown=shown_commits, total=len(data["commits"]))
    parts.append(f'<text x="80" y="942" class="mono muted" font-size="14">{xml_escape(scope)}</text>')
    parts.append(f'<text x="80" y="968" class="mono muted" font-size="16">{xml_escape(labels["draft"])}</text>')
    parts.append("</svg>\n")
    return "".join(parts)


def render_social_svg(data: dict[str, Any], locale: str, theme: str) -> str:
    palette = THEMES[theme]
    labels = LOCALES[locale]
    headline, dek = locale_text(data, locale)
    summary = data["summary"]
    headline_lines = svg_text_lines(headline, 27, 3)
    highlighted = select_highlights(data)
    if highlighted:
        evidence = " · ".join(commit["short_sha"] for commit in highlighted)
    else:
        evidence = f'{data["range"]["from_sha"][:7]}..{data["range"]["to_sha"][:7]}'
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" role="img" aria-labelledby="title desc">',
        f'<title id="title">{xml_escape(headline)}</title><desc id="desc">{xml_escape(dek)}</desc>',
        f'<rect width="1200" height="630" fill="{palette["paper"]}"/>',
        f'<rect x="42" y="42" width="1116" height="546" fill="none" stroke="{palette["ink"]}" stroke-width="4"/>',
        f'<style>text{{fill:{palette["ink"]};font-family:Georgia,serif}}.mono{{font-family:ui-monospace,monospace}}.muted{{fill:{palette["muted"]}}}.accent{{fill:{palette["accent"]}}}</style>',
        f'<text x="80" y="95" class="mono accent" font-size="18" font-weight="700" letter-spacing="4">'
        f'{xml_escape(ellipsize(data["repository"]["name"].upper(), 32))} · {xml_escape(labels["release"].upper())} '
        f'{xml_escape(ellipsize(data["version"].upper(), 32))}</text>',
    ]
    y = 195
    for line in headline_lines:
        parts.append(f'<text x="80" y="{y}" font-size="68" font-weight="700" letter-spacing="-2">{xml_escape(line)}</text>')
        y += 72
    parts.extend(
        [
            f'<path d="M80 465H1120" stroke="{palette["ink"]}" stroke-width="3"/>',
            f'<text x="80" y="525" font-size="34" font-weight="700">{summary["commit_count"]}</text>',
            f'<text x="135" y="524" class="mono muted" font-size="16">{xml_escape(labels["commits_short"])}</text>',
            f'<text x="390" y="525" font-size="34" font-weight="700">{summary["files_changed"]}</text>',
            f'<text x="445" y="524" class="mono muted" font-size="16">{xml_escape(labels["files_short"])}</text>',
            f'<text x="720" y="525" font-size="34" font-weight="700">+{summary["additions"]} / -{summary["deletions"]}</text>',
            f'<text x="80" y="558" class="mono accent" font-size="14">{xml_escape(labels["social_evidence"])} · {xml_escape(evidence)}</text>',
            f'<text x="80" y="580" class="mono muted" font-size="13">{xml_escape(labels["social_draft"])}</text>',
            "</svg>\n",
        ]
    )
    return "".join(parts)


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


def render_all(data: dict[str, Any], out_dir: Path, locale: str, theme: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    files = {
        "release-data.json": canonical,
        "RELEASE_NOTES_DRAFT.md": render_markdown(data, locale),
        "release-front-page.html": render_html(data, locale, theme),
        "release-front-page.svg": render_front_page_svg(data, locale, theme),
        "release-social-card.svg": render_social_svg(data, locale, theme),
    }
    for name, content in files.items():
        atomic_write_text(out_dir / name, content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to release-data.json")
    parser.add_argument("--out-dir", required=True, help="Directory for generated release files")
    parser.add_argument("--locale", choices=sorted(LOCALES), default="en")
    parser.add_argument("--theme", choices=sorted(THEMES), default="broadsheet")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        input_path = Path(args.input).expanduser().resolve()
        raw_out_dir = Path(args.out_dir).expanduser()
        if raw_out_dir.is_symlink():
            raise RenderError("output directory must not be a symbolic link")
        out_dir = raw_out_dir.resolve(strict=False)
        if input_path == (out_dir / "release-data.json").resolve(strict=False):
            raise RenderError("input JSON must not collide with rendered release-data.json")
        data = load_data(input_path)
        render_all(data, out_dir, args.locale, args.theme)
    except (RenderError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
