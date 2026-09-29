from __future__ import annotations

import importlib.util
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "release-front-page"
COLLECTOR = SKILL / "scripts" / "collect_release.py"
RENDERER = SKILL / "scripts" / "render_release.py"
EXAMPLE_DATA = ROOT / "examples" / "sample-release" / "release-data.json"
EXAMPLE_BUILDER = ROOT / "examples" / "sample-release" / "build_fixture.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


collector = load_module("collector", COLLECTOR)
renderer = load_module("renderer", RENDERER)


class TemporaryRepository:
    def __init__(self, root: Path):
        self.path = root / "repo"
        self.path.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            {
                "GIT_AUTHOR_NAME": "Release Tester",
                "GIT_AUTHOR_EMAIL": "private@example.test",
                "GIT_COMMITTER_NAME": "Release Tester",
                "GIT_COMMITTER_EMAIL": "private@example.test",
                "GIT_AUTHOR_DATE": "2024-01-01T00:00:00Z",
                "GIT_COMMITTER_DATE": "2024-01-01T00:00:00Z",
            }
        )
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Release Tester")
        self.git("config", "user.email", "private@example.test")

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            env=self.env,
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def commit(self, subject: str, filename: str, content: str, body: str | None = None) -> str:
        path = self.path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git("add", "-A")
        args = ["commit", "-m", subject]
        if body is not None:
            args.extend(["-m", body])
        self.git(*args)
        return self.git("rev-parse", "HEAD").stdout.strip()


class CollectorUnitTests(unittest.TestCase):
    def test_conventional_and_breaking_classification(self):
        feat = collector.parse_subject("feat(cli): accept stdin", "")
        self.assertEqual(feat["category"], "Features")
        self.assertEqual(feat["scope"], "cli")

        breaking = collector.parse_subject(
            "feat(api)!: remove legacy route", "BREAKING CHANGE: use /v2 instead"
        )
        self.assertEqual(breaking["category"], "Breaking Changes")
        self.assertTrue(breaking["breaking"])
        self.assertEqual(breaking["migration_note"], "use /v2 instead")

        reverted = collector.parse_subject('Revert "feat: ship rocket"', "")
        self.assertTrue(reverted["revert"])
        self.assertEqual(reverted["category"], "Other")

    def test_pr_number_pattern_is_conservative(self):
        self.assertEqual(collector.PR_RE.search("fix: handle nil (#42)").group("number"), "42")
        self.assertIsNone(collector.PR_RE.search("docs: heading #42is-not-a-pr"))

    def test_batched_metadata_parser_scales_without_per_field_git_calls(self):
        for count in (500, 2000):
            records = []
            for index in range(count):
                sha = f"{index + 1:040x}"
                records.append(f"{sha}\x00feat: change {index}\x00body\x00{'0' * 40}\x00Tester\x00\n")
            with self.subTest(count=count), mock.patch.object(
                collector, "git", return_value="".join(records)
            ) as git_mock:
                parsed = collector.read_commit_records(Path("/unused"), "a" * 40, "b" * 40, False)
                self.assertEqual(len(parsed), count)
                git_mock.assert_called_once()

    def test_nul_numstat_preserves_unusual_paths(self):
        parsed = collector.parse_numstat("2\t1\tdir/name\twith\nnewline.py\x00-\t-\tbinary.bin\x00")
        self.assertEqual(parsed[0]["path"], "binary.bin")
        self.assertTrue(parsed[0]["binary"])
        self.assertEqual(parsed[1]["path"], "dir/name\twith\nnewline.py")
        self.assertEqual(parsed[1]["additions"], 2)

    def test_commit_text_sanitizer_removes_identity_and_unsafe_controls(self):
        value = "Fix\x0b parser for person@example.test\nHelped-by: Private <private@example.test>"
        sanitized = collector.redact_identity_text(value)
        self.assertEqual(sanitized, "Fix� parser for [redacted-email]")


class CollectorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = TemporaryRepository(self.root)
        self.repo.commit("chore: initial scaffold", "README.md", "# Demo\n")
        self.repo.git("tag", "v1.0.0")
        self.repo.commit("feat(cli): accept stdin", "src/cli.py", "def read():\n    return input()\n")
        self.repo.commit("fix: 修复空值 <edge>", "src/cli.py", "def read():\n    return input() or None\n")
        self.repo.commit(
            "feat(api)!: remove legacy route",
            "src/api.py",
            "ROUTE = '/v2'\n",
            "BREAKING CHANGE: replace /v1 with /v2",
        )
        self.repo.commit("docs: explain migration", "docs/migration.md", "Use /v2.\n")
        self.repo.git("tag", "v2.0.0")

    def tearDown(self):
        self.temp.cleanup()

    def run_collector(self, *extra: str, output: Path | None = None):
        output = output or self.root / "release.json"
        return subprocess.run(
            [
                sys.executable,
                str(COLLECTOR),
                "--repo",
                str(self.repo.path),
                "--from",
                "v1.0.0",
                "--to",
                "v2.0.0",
                "--version",
                "v2.0.0",
                "--output",
                str(output),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        ), output

    def test_collects_range_categories_stats_and_unicode(self):
        result, output = self.run_collector()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], "1.0")
        self.assertEqual(data["summary"]["commit_count"], 4)
        self.assertEqual(data["summary"]["breaking_count"], 1)
        self.assertEqual(data["summary"]["categories"]["Features"], 1)
        self.assertEqual(data["summary"]["categories"]["Fixes"], 1)
        self.assertEqual(data["summary"]["change_basis"], "net_ref_diff")
        self.assertEqual(data["summary"]["files_changed"], 3)
        self.assertEqual(data["summary"]["additions"], 4)
        self.assertEqual(data["summary"]["deletions"], 0)
        self.assertIn("修复空值", output.read_text(encoding="utf-8"))
        self.assertEqual(data["commits"][0]["files"][0]["path"], "src/cli.py")
        self.assertIsInstance(data["commits"][0]["stats"]["additions"], int)

    def test_output_is_deterministic_and_has_no_absolute_path(self):
        first = self.root / "one.json"
        second = self.root / "two.json"
        first_result, _ = self.run_collector(output=first)
        second_result, _ = self.run_collector(output=second)
        self.assertEqual(first_result.returncode, 0, first_result.stderr)
        self.assertEqual(second_result.returncode, 0, second_result.stderr)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertNotIn(str(self.root), first.read_text(encoding="utf-8"))

    def test_contributors_are_opt_in_and_never_include_email(self):
        result, output = self.run_collector("--include-contributors")
        self.assertEqual(result.returncode, 0, result.stderr)
        content = output.read_text(encoding="utf-8")
        data = json.loads(content)
        self.assertEqual(data["contributors"], [{"commits": 4, "name": "Release Tester"}])
        self.assertNotIn("private@example.test", content)

        without, output_without = self.run_collector(output=self.root / "without.json")
        self.assertEqual(without.returncode, 0, without.stderr)
        self.assertEqual(json.loads(output_without.read_text())["contributors"], [])

    def test_commit_trailers_and_email_shaped_text_are_redacted(self):
        self.repo.commit(
            "fix: hide reporter leak@example.test",
            "src/privacy.py",
            "SAFE = True\n",
            "Details for person@example.test\n\nCo-authored-by: Private Person <private@example.test>\nSigned-off-by: Other <other@example.test>",
        )
        self.repo.git("tag", "v2.0.1")
        result, output = self.run_collector("--to", "v2.0.1", "--include-contributors")
        self.assertEqual(result.returncode, 0, result.stderr)
        content = output.read_text(encoding="utf-8")
        self.assertNotIn("example.test", content)
        self.assertNotIn("Co-authored-by", content)
        self.assertNotIn("Signed-off-by", content)
        self.assertIn("[redacted-email]", content)

    def test_gh_setup_failure_is_recorded_without_blocking_offline_collection(self):
        args = collector.build_parser().parse_args(
            [
                "--repo", str(self.repo.path),
                "--from", "v1.0.0",
                "--to", "v2.0.0",
                "--version", "v2.0.0",
                "--output", str(self.root / "unused.json"),
                "--use-gh",
            ]
        )
        with mock.patch.object(collector, "validate_gh", return_value=(None, "gh is not installed")):
            data = collector.collect(args)
        self.assertEqual(data["github_enrichment"], {
            "requested": True,
            "attempted": 0,
            "succeeded": 0,
            "failures": [],
            "failure_reason": "gh is not installed",
        })

    def test_refuses_to_overwrite_tracked_file(self):
        output = self.repo.path / "README.md"
        result, _ = self.run_collector(output=output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tracked repository file", result.stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), "# Demo\n")

    def test_empty_range_is_successful(self):
        output = self.root / "empty.json"
        result = subprocess.run(
            [
                sys.executable,
                str(COLLECTOR),
                "--repo",
                str(self.repo.path),
                "--from",
                "v2.0.0",
                "--to",
                "v2.0.0",
                "--version",
                "v2.0.0",
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text())["commits"], [])

    def test_invalid_ref_and_non_git_directory_fail_cleanly(self):
        bad_ref, _ = self.run_collector("--to", "missing-ref")
        self.assertNotEqual(bad_ref.returncode, 0)
        self.assertIn("invalid Git ref", bad_ref.stderr)

        plain = self.root / "plain"
        plain.mkdir()
        result = subprocess.run(
            [
                sys.executable,
                str(COLLECTOR),
                "--repo",
                str(plain),
                "--from",
                "a",
                "--to",
                "b",
                "--version",
                "v0",
                "--output",
                str(self.root / "bad.json"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Git", result.stderr)

    def test_merge_commits_are_opt_in(self):
        self.repo.git("checkout", "-b", "topic")
        self.repo.commit("feat: topic feature", "src/topic.py", "TOPIC = True\n")
        self.repo.git("checkout", "main")
        self.repo.commit("docs: main note", "docs/main.md", "Main.\n")
        self.repo.git("merge", "--no-ff", "topic", "-m", "Merge topic")
        self.repo.git("tag", "v2.1.0")

        without = self.root / "no-merges.json"
        with_merges = self.root / "with-merges.json"
        base = [
            sys.executable,
            str(COLLECTOR),
            "--repo",
            str(self.repo.path),
            "--from",
            "v2.0.0",
            "--to",
            "v2.1.0",
            "--version",
            "v2.1.0",
        ]
        one = subprocess.run([*base, "--output", str(without)], capture_output=True, text=True)
        two = subprocess.run(
            [*base, "--output", str(with_merges), "--include-merges"], capture_output=True, text=True
        )
        self.assertEqual(one.returncode, 0, one.stderr)
        self.assertEqual(two.returncode, 0, two.stderr)
        self.assertEqual(json.loads(without.read_text())["summary"]["merge_count"], 0)
        self.assertEqual(json.loads(with_merges.read_text())["summary"]["merge_count"], 1)

    def test_real_revert_is_preserved_as_other(self):
        reverted_sha = self.repo.commit("feat: temporary switch", "src/switch.py", "ENABLED = True\n")
        self.repo.git("revert", "--no-edit", reverted_sha)
        self.repo.git("tag", "v2.0.1")
        output = self.root / "revert.json"
        result = subprocess.run(
            [
                sys.executable,
                str(COLLECTOR),
                "--repo",
                str(self.repo.path),
                "--from",
                "v2.0.0",
                "--to",
                "v2.0.1",
                "--version",
                "v2.0.1",
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(output.read_text())
        self.assertEqual(data["summary"]["revert_count"], 1)
        self.assertEqual(data["commits"][-1]["category"], "Other")


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_renderer(self, *extra: str, out_dir: Path | None = None):
        out_dir = out_dir or self.root / "rendered"
        result = subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--input",
                str(EXAMPLE_DATA),
                "--out-dir",
                str(out_dir),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result, out_dir

    def test_generates_all_outputs_and_valid_xml(self):
        result, out_dir = self.run_renderer()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {
            "release-data.json",
            "RELEASE_NOTES_DRAFT.md",
            "release-front-page.html",
            "release-front-page.svg",
            "release-social-card.svg",
        }
        self.assertEqual({path.name for path in out_dir.iterdir()}, expected)
        for name in ["release-front-page.svg", "release-social-card.svg"]:
            ET.parse(out_dir / name)
            content = (out_dir / name).read_text(encoding="utf-8")
            self.assertNotIn("<image", content)
            self.assertNotIn("href=", content)
        html_content = (out_dir / "release-front-page.html").read_text(encoding="utf-8")
        self.assertNotIn("<script", html_content)
        self.assertNotIn("@import", html_content)
        self.assertNotIn("url(", html_content)

    def test_chinese_locale_uses_same_structured_data(self):
        result, out_dir = self.run_renderer("--locale", "zh-CN")
        self.assertEqual(result.returncode, 0, result.stderr)
        notes = (out_dir / "RELEASE_NOTES_DRAFT.md").read_text(encoding="utf-8")
        copied = json.loads((out_dir / "release-data.json").read_text(encoding="utf-8"))
        original = json.loads(EXAMPLE_DATA.read_text(encoding="utf-8"))
        self.assertIn("管道进场，旧参数退场", notes)
        self.assertIn("**破坏性变更**", notes)
        self.assertNotIn("**BREAKING**", notes)
        self.assertEqual(copied, original)
        social = (out_dir / "release-social-card.svg").read_text(encoding="utf-8")
        self.assertIn("发布 V2.0.0", social)
        self.assertIn("提交", social)
        evidence_shas = " · ".join(
            item["short_sha"] for item in (original["commits"][0], original["commits"][-1])
        )
        self.assertIn(f"证据 · {evidence_shas}", social)
        self.assertIn("发布前请人工核对", social)

    def test_outputs_are_repeatable_and_escape_special_characters(self):
        first_result, first = self.run_renderer(out_dir=self.root / "first")
        second_result, second = self.run_renderer(out_dir=self.root / "second")
        self.assertEqual(first_result.returncode, 0, first_result.stderr)
        self.assertEqual(second_result.returncode, 0, second_result.stderr)
        for name in ["release-data.json", "RELEASE_NOTES_DRAFT.md", "release-front-page.html", "release-front-page.svg", "release-social-card.svg"]:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        ET.parse(first / "release-front-page.svg")
        self.assertIn("&lt;edge&gt;", (first / "release-front-page.svg").read_text(encoding="utf-8"))

    def test_invalid_json_fails_without_partial_output(self):
        invalid = self.root / "invalid.json"
        invalid.write_text("{}", encoding="utf-8")
        out_dir = self.root / "invalid-output"
        result = subprocess.run(
            [sys.executable, str(RENDERER), "--input", str(invalid), "--out-dir", str(out_dir)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required keys", result.stderr)
        self.assertFalse(out_dir.exists())

    def test_unknown_schema_and_input_output_collision_are_rejected(self):
        data = json.loads(EXAMPLE_DATA.read_text(encoding="utf-8"))
        data["schema_version"] = "2.0"
        invalid = self.root / "schema.json"
        invalid.write_text(json.dumps(data), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(RENDERER), "--input", str(invalid), "--out-dir", str(self.root / "schema-out")],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported schema_version", result.stderr)

        collision_dir = self.root / "collision"
        collision_dir.mkdir()
        collision = collision_dir / "release-data.json"
        collision.write_bytes(EXAMPLE_DATA.read_bytes())
        result = subprocess.run(
            [sys.executable, str(RENDERER), "--input", str(collision), "--out-dir", str(collision_dir)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("collide", result.stderr)

    def test_strict_schema_rejects_bad_stats_enrichment_and_missing_highlight(self):
        base = json.loads(EXAMPLE_DATA.read_text(encoding="utf-8"))
        cases = []

        bad_stats = copy.deepcopy(base)
        bad_stats["summary"]["additions"] = -1
        cases.append((bad_stats, "non-negative integer"))

        bad_enrichment = copy.deepcopy(base)
        bad_enrichment["github_enrichment"].update({"attempted": 1, "succeeded": 0, "failures": []})
        cases.append((bad_enrichment, "counts are inconsistent"))

        missing_enrichment_reason = copy.deepcopy(base)
        del missing_enrichment_reason["github_enrichment"]["failure_reason"]
        cases.append((missing_enrichment_reason, "failure_reason is required"))

        mismatched_commit_stats = copy.deepcopy(base)
        mismatched_commit_stats["commits"][0]["stats"]["additions"] += 1
        cases.append((mismatched_commit_stats, "stats must match files"))

        missing_highlight = copy.deepcopy(base)
        del missing_highlight["commits"][0]["highlight"]
        cases.append((missing_highlight, "highlight must be boolean"))

        for index, (payload, expected) in enumerate(cases):
            path = self.root / f"strict-{index}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.subTest(expected=expected), self.assertRaisesRegex(renderer.RenderError, expected):
                renderer.load_data(path)

    def test_markdown_injection_and_untrusted_pr_url_are_rejected(self):
        data = json.loads(EXAMPLE_DATA.read_text(encoding="utf-8"))
        data["editorial"]["en"]["headline"] = "Bad [link](https://attacker.invalid)"
        data["commits"][0]["summaries"]["en"] = "![remote](https://attacker.invalid/x.png)\n# injected"
        rendered = renderer.render_markdown(data, "en")
        self.assertNotIn("](", rendered)
        self.assertNotIn("\n# injected", rendered)
        self.assertIn("\\[link\\]", rendered)

        bad = copy.deepcopy(data)
        bad["repository"]["remote_slug"] = "gezi71/release-front-page"
        bad["commits"][0]["provenance"]["pull_request"] = {
            "number": 7,
            "url": "https://attacker.invalid/gezi71/release-front-page/pull/7",
        }
        invalid = self.root / "bad-pr.json"
        invalid.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(renderer.RenderError):
            renderer.load_data(invalid)

    def test_explicit_highlights_and_visible_truncation(self):
        data = json.loads(EXAMPLE_DATA.read_text(encoding="utf-8"))
        self.assertEqual(len(renderer.select_highlights(data)), 2)
        for item in data["commits"]:
            item["highlight"] = False
        self.assertEqual(renderer.select_highlights(data), [])

        template = json.loads(EXAMPLE_DATA.read_text(encoding="utf-8"))["commits"][0]
        many = []
        for index in range(24):
            item = copy.deepcopy(template)
            sha = f"{index + 1:040x}"
            item["sha"] = sha
            item["short_sha"] = sha[:7]
            item["provenance"] = {"commit": sha, "pull_request": None}
            item["summary"] = f"Change {index}"
            item["summaries"] = {"en": f"Change {index}", "zh-CN": f"变更 {index}"}
            many.append(item)
        data["commits"] = many
        data["summary"]["commit_count"] = len(many)
        svg = renderer.render_front_page_svg(data, "en", "broadsheet")
        self.assertIn("+21 more", svg)
        self.assertIn("Poster shows 3 of 24 commits", svg)
        html_page = renderer.render_html(data, "en", "broadsheet")
        self.assertIn("+12 more", html_page)
        self.assertIn("Page shows 12 of 24 commits", html_page)
        self.assertIn("display:grid;grid-template-columns:repeat(2", html_page)

    def test_long_version_and_headline_are_visibly_truncated_in_fixed_size_svg(self):
        data = json.loads(EXAMPLE_DATA.read_text(encoding="utf-8"))
        data["version"] = "v" + "1234567890" * 12
        data["editorial"]["en"]["headline"] = "An evidence backed headline " * 20
        front = renderer.render_front_page_svg(data, "en", "broadsheet")
        social = renderer.render_social_svg(data, "en", "modern")
        self.assertIn("…", front)
        self.assertIn("…", social)
        self.assertNotIn(data["version"].upper(), front)
        self.assertNotIn(data["version"].upper(), social)

    def test_large_release_rendering_handles_500_and_2000_commits(self):
        base = json.loads(EXAMPLE_DATA.read_text(encoding="utf-8"))
        template = base["commits"][0]
        for count in (500, 2000):
            data = copy.deepcopy(base)
            commits = []
            for index in range(count):
                item = copy.deepcopy(template)
                sha = f"{index + 1:040x}"
                item["sha"] = sha
                item["short_sha"] = sha[:7]
                item["provenance"] = {"commit": sha, "pull_request": None}
                item["summaries"] = {"en": f"Change {index}", "zh-CN": f"变更 {index}"}
                commits.append(item)
            data["commits"] = commits
            data["summary"]["commit_count"] = count
            self.assertIn(f"of {count} commits", renderer.render_front_page_svg(data, "en", "modern"))

    def test_checked_in_example_is_rebuilt_byte_for_byte(self):
        generated = self.root / "generated"
        result = subprocess.run(
            [sys.executable, str(EXAMPLE_BUILDER), "--out-dir", str(generated)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in (
            "release-data.json",
            "RELEASE_NOTES_DRAFT.md",
            "release-front-page.html",
            "release-front-page.svg",
            "release-social-card.svg",
        ):
            self.assertEqual((generated / name).read_bytes(), (EXAMPLE_DATA.parent / name).read_bytes(), name)


class SkillStructureTests(unittest.TestCase):
    def test_frontmatter_and_agent_metadata_are_minimal(self):
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = skill_text.split("---", 2)[1]
        keys = [line.split(":", 1)[0] for line in frontmatter.splitlines() if ":" in line]
        self.assertEqual(keys, ["name", "description"])
        metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$release-front-page", metadata)
        self.assertNotIn("dependencies:", metadata)
        self.assertNotIn("policy:", metadata)

    def test_skill_is_cwd_independent(self):
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("directory containing this `SKILL.md`", skill_text)
        self.assertIn("$SKILL_ROOT/scripts/collect_release.py", skill_text)
        self.assertIn("$SKILL_ROOT/scripts/render_release.py", skill_text)

    def test_plugin_and_marketplace_contracts(self):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "release-front-page")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["author"]["name"], "gezi71")
        self.assertEqual(manifest["license"], "MIT")
        self.assertEqual(manifest["skills"], "./skills/")
        interface = manifest["interface"]
        self.assertEqual(interface["developerName"], "gezi71")
        self.assertEqual(interface["category"], "Developer Tools")
        self.assertEqual(interface["capabilities"], ["Read", "Write"])
        self.assertLessEqual(len(interface["defaultPrompt"]), 3)
        self.assertTrue(all("$release-front-page" in prompt for prompt in interface["defaultPrompt"]))

        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(marketplace["plugins"]), 1)
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "release-front-page")
        self.assertEqual(entry["source"], {
            "source": "url",
            "url": "https://github.com/gezi71/release-front-page.git",
            "ref": "v1.0.0",
        })
        self.assertEqual(entry["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        self.assertNotIn("products", entry["policy"])

    def test_release_engineering_files_and_pinned_ci(self):
        required = [
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            ".github/ISSUE_TEMPLATE/bug.yml",
            ".github/ISSUE_TEMPLATE/feature.yml",
            ".github/pull_request_template.md",
            ".github/dependabot.yml",
        ]
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("timeout-minutes:", workflow)
        self.assertIn("windows-latest", workflow)
        self.assertIn("3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1", workflow)
        self.assertIn("5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0", workflow)
        self.assertFalse((ROOT / ".DS_Store").exists())


if __name__ == "__main__":
    unittest.main()
