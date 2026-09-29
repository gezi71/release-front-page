#!/usr/bin/env python3
"""Rebuild the checked-in sample release from a deterministic local Git history."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


EXAMPLE_DIR = Path(__file__).resolve().parent
ROOT = EXAMPLE_DIR.parents[1]
COLLECTOR = ROOT / "skills" / "release-front-page" / "scripts" / "collect_release.py"
RENDERER = ROOT / "skills" / "release-front-page" / "scripts" / "render_release.py"


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "command failed")


def write(repo: Path, relative: str, content: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def commit(repo: Path, env: dict[str, str], timestamp: str, subject: str, body: str | None = None) -> None:
    commit_env = env.copy()
    commit_env["GIT_AUTHOR_DATE"] = timestamp
    commit_env["GIT_COMMITTER_DATE"] = timestamp
    run(["git", "add", "-A"], repo, commit_env)
    command = ["git", "commit", "-m", subject]
    if body:
        command.extend(["-m", body])
    run(command, repo, commit_env)


def create_history(repo: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Sample Maintainer",
            "GIT_AUTHOR_EMAIL": "sample@example.invalid",
            "GIT_COMMITTER_NAME": "Sample Maintainer",
            "GIT_COMMITTER_EMAIL": "sample@example.invalid",
        }
    )
    run(["git", "init", "-b", "main"], repo, env)
    write(repo, "README.md", "# Sample CLI\n\nA deterministic release fixture.\n")
    write(
        repo,
        "src/cli.py",
        "from pathlib import Path\n\n\n"
        "def load_config(path):\n"
        "    return Path(path).read_text(encoding='utf-8')\n",
    )
    commit(repo, env, "2024-01-01T00:00:00Z", "chore: establish sample CLI")
    run(["git", "tag", "v1.4.0"], repo, env)

    write(
        repo,
        "src/cli.py",
        "from pathlib import Path\n\n"
        "import sys\n\n\n"
        "def load_config(path, stdin=None):\n"
        "    if path == '-':\n"
        "        return (stdin if stdin is not None else sys.stdin).read()\n"
        "    return Path(path).read_text(encoding='utf-8')\n",
    )
    write(
        repo,
        "tests/test_cli.py",
        "import io\n"
        "import tempfile\n"
        "import unittest\n"
        "from pathlib import Path\n\n"
        "from src.cli import load_config\n\n\n"
        "class CliTests(unittest.TestCase):\n"
        "    def test_dash_reads_stdin(self):\n"
        "        self.assertEqual(load_config('-', io.StringIO('profile: demo\\n')), 'profile: demo\\n')\n\n"
        "    def test_path_reads_utf8_file(self):\n"
        "        with tempfile.TemporaryDirectory() as directory:\n"
        "            path = Path(directory) / 'config.yml'\n"
        "            path.write_text('profile: demo\\n', encoding='utf-8')\n"
        "            self.assertEqual(load_config(str(path)), 'profile: demo\\n')\n",
    )
    commit(repo, env, "2024-01-02T00:00:00Z", "feat(cli): accept configuration from stdin")

    write(
        repo,
        "src/parser.py",
        "def parse_scalar(raw):\n"
        "    value = raw.strip()\n"
        "    if value.startswith('<') and value.endswith('>'):\n"
        "        return value\n"
        "    if len(value) >= 2 and value[0] == value[-1] and value[0] in '\\\"\\\'':\n"
        "        return value[1:-1]\n"
        "    return value\n",
    )
    write(
        repo,
        "tests/test_parser.py",
        "import unittest\n\n"
        "from src.parser import parse_scalar\n\n\n"
        "class ParserTests(unittest.TestCase):\n"
        "    def test_edge_scalar_is_preserved(self):\n"
        "        self.assertEqual(parse_scalar('  <edge>  '), '<edge>')\n\n"
        "    def test_quoted_scalar_is_unquoted(self):\n"
        "        self.assertEqual(parse_scalar('\\\"edge\\\"'), 'edge')\n",
    )
    commit(repo, env, "2024-01-03T00:00:00Z", "fix: preserve <edge> values in YAML")

    write(
        repo,
        "src/options.py",
        "DEFAULT_PROFILE = 'default'\nSUPPORTED_OPTIONS = ('--profile',)\n",
    )
    write(
        repo,
        "docs/migration.md",
        "Replace `--legacy` with `--profile default`.\n",
    )
    write(
        repo,
        "src/options.py",
        "import argparse\n\n"
        "DEFAULT_PROFILE = 'default'\n\n\n"
        "def build_parser():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--profile', default=DEFAULT_PROFILE)\n"
        "    return parser\n",
    )
    write(
        repo,
        "tests/test_options.py",
        "import contextlib\n"
        "import io\n"
        "import unittest\n\n"
        "from src.options import build_parser\n\n\n"
        "class OptionTests(unittest.TestCase):\n"
        "    def test_named_profile_is_supported(self):\n"
        "        self.assertEqual(build_parser().parse_args(['--profile', 'demo']).profile, 'demo')\n\n"
        "    def test_legacy_option_is_rejected(self):\n"
        "        with contextlib.redirect_stderr(io.StringIO()):\n"
        "            with self.assertRaises(SystemExit):\n"
        "                build_parser().parse_args(['--legacy'])\n",
    )
    commit(
        repo,
        env,
        "2024-01-04T00:00:00Z",
        "feat(cli)!: replace the legacy option",
        "BREAKING CHANGE: replace --legacy with --profile default",
    )
    run(["git", "tag", "v2.0.0"], repo, env)
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], repo)


def enrich(data: dict) -> None:
    data["editorial"] = {
        "en": {
            "headline": "Pipes in. Legacy flags out.",
            "dek": "Configuration can now arrive by pipe, while named profiles make the old CLI contract explicit.",
        },
        "zh-CN": {
            "headline": "管道进场，旧参数退场",
            "dek": "配置现在可以通过管道输入，命名配置档也让旧版 CLI 契约正式退场。",
        },
    }
    copy = {
        "feat(cli): accept configuration from stdin": (
            "The CLI now accepts configuration from stdin.",
            "CLI 现在可以从标准输入读取配置。",
            True,
        ),
        "fix: preserve <edge> values in YAML": (
            "YAML parsing now preserves <edge> values.",
            "YAML 解析现在会保留 <edge> 值。",
            False,
        ),
        "feat(cli)!: replace the legacy option": (
            "Named profiles replace the legacy CLI option.",
            "命名配置档取代了旧版 CLI 选项。",
            True,
        ),
    }
    for item in data["commits"]:
        en, zh, highlight = copy[item["subject"]]
        item["summaries"] = {"en": en, "zh-CN": zh}
        item["confidence"] = "high"
        item["highlight"] = highlight
    data["limitations"] = [
        "Sample claims trace to the bundled fixture's commits, code, tests, and migration document.",
        "The fixture builder runs the bundled tests; the release collector never executes target-project code.",
        "The release still requires maintainer approval before publication.",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(EXAMPLE_DIR), help="Destination for generated sample files")
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-front-page-fixture-") as temporary:
        temporary_root = Path(temporary)
        repo = temporary_root / "sample-cli"
        repo.mkdir()
        create_history(repo)
        raw_data = temporary_root / "collected.json"
        run(
            [
                sys.executable,
                str(COLLECTOR),
                "--repo",
                str(repo),
                "--from",
                "v1.4.0",
                "--to",
                "v2.0.0",
                "--version",
                "v2.0.0",
                "--output",
                str(raw_data),
            ],
            ROOT,
        )
        data = json.loads(raw_data.read_text(encoding="utf-8"))
        enrich(data)
        edited_data = temporary_root / "release-data.json"
        edited_data.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        run(
            [
                sys.executable,
                str(RENDERER),
                "--input",
                str(edited_data),
                "--out-dir",
                str(out_dir),
                "--locale",
                "en",
                "--theme",
                "broadsheet",
            ],
            ROOT,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
