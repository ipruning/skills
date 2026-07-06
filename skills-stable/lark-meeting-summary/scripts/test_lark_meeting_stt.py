#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "jinja2>=3.1.6",
#   "pydantic>=2.13.0",
#   "tiktoken>=0.13.0",
#   "typer>=0.16.0",
# ]
# ///
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("lark_meeting_stt.py")
SPEC = importlib.util.spec_from_file_location("lark_meeting_stt", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def patch_module_attr(attr_name: str, value: object) -> None:
    setattr(mod, attr_name, value)


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        cwd=SCRIPT.parent,
        check=False,
    )


class LarkMeetingSttTests(unittest.TestCase):
    def test_selected_file_values_ignores_comments_and_blanks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "selected.txt"
            file_path.write_text("\n# comment\nobc1\n  obc2  \n", encoding="utf-8")
            self.assertEqual(mod.selected_file_values(file_path), ["obc1", "obc2"])

    def test_merge_minute_combines_sources_and_keeps_first_title(self) -> None:
        minutes: dict[str, dict] = {}
        mod.merge_minute(
            minutes,
            "obc1",
            source="minutes_owner_search",
            item={"title": "标题 A", "app_link": "https://example.com/a"},
        )
        mod.merge_minute(
            minutes,
            "obc1",
            source="vc_minute_lookup",
            item={"title": "标题 B", "app_link": "https://example.com/b"},
            meeting_id="m1",
            calendar_event_id="e1",
        )
        self.assertEqual(minutes["obc1"]["title"], "标题 A")
        self.assertEqual(minutes["obc1"]["sources"], ["minutes_owner_search", "vc_minute_lookup"])
        self.assertEqual(minutes["obc1"]["meeting_ids"], ["m1"])
        self.assertEqual(minutes["obc1"]["calendar_event_ids"], ["e1"])
        self.assertEqual(minutes["obc1"]["app_links"], ["https://example.com/a", "https://example.com/b"])

    def test_duplicate_groups_rank_hash_prefix_and_first_line(self) -> None:
        metas = [
            self.meta("a", "会议 A", sha="same", prefix="p1", first="t|10min", lines=100),
            self.meta("b", "会议 B", sha="same", prefix="p2", first="u|11min", lines=101),
            self.meta("c", "会议 C", sha="c", prefix="same-prefix", first="v|12min", lines=120),
            self.meta("d", "会议 D", sha="d", prefix="same-prefix", first="w|13min", lines=121),
            self.meta("e", "小程序 AI 能力初始化", sha="e", prefix="e-prefix", first="x|13min 53s", lines=146),
            self.meta("f", "小程序功能开发方案讨论", sha="f", prefix="f-prefix", first="x|13min 53s", lines=146),
        ]
        groups = mod.build_duplicate_groups(metas)
        kinds = [group["kind"] for group in groups]
        self.assertIn("强重复", kinds)
        self.assertIn("高度可疑", kinds)
        weak = [group for group in groups if group["kind"] == "弱可疑"]
        self.assertTrue(any(set(group["minute_tokens"]) == {"e", "f"} for group in weak))
        self.assertTrue(all("recommended_exclude" not in json.dumps(group, ensure_ascii=False) for group in groups))

    def test_coverage_is_discovery_report_not_pull_status(self) -> None:
        report = {
            "run": {"start": "2099-01-10", "end": "2099-01-11", "created_at": "now"},
            "identity": {"userName": "u", "openId": "ou", "tokenStatus": "valid", "verified": True},
            "counts": {},
            "coverage": {},
        }
        markdown = mod.coverage_markdown(report)
        self.assertIn("运行 `pull --run <run>`", markdown)
        self.assertIn("覆盖报告", markdown)
        self.assertNotIn("拉取失败", markdown)
        self.assertNotIn("不可导出", markdown)

    def test_prompt_file_name_is_ascii(self) -> None:
        name = mod.prompt_file_name({"minute_token": "obc1", "title": "每周 AI Sync"})
        self.assertEqual(name, "obc1-ai-sync.prompt.md")
        self.assertTrue(name.isascii())

    def test_default_template_is_chinese_and_keeps_meeting_title(self) -> None:
        rendered = mod.render_prompt(
            template_path=mod.DEFAULT_TEMPLATE,
            transcript_text="说话人 00:00\n讨论文件上传入口。",
            meta={"minute_token": "obc1", "title": "每周 AI Sync"},
        )
        self.assertIn("请根据上面的飞书妙记文字记录写会议总结", rendered)
        self.assertIn("每段只承载一个论点", rendered)
        self.assertNotIn("每节不少于", rendered)
        self.assertIn("每周 AI Sync", rendered)

    def test_prompts_rebuilds_prompt_dir_and_uses_selected_for_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            minute_dir = base / "minutes" / "obc1"
            minute_dir.mkdir(parents=True)
            (minute_dir / "transcript.txt").write_text("说话人 00:00\n内容", encoding="utf-8")
            (minute_dir / "meta.json").write_text(
                json.dumps({"minute_token": "obc1", "title": "测试会议"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (base / "selected.txt").write_text("obc1\n", encoding="utf-8")
            prompts_dir = base / "prompts"
            prompts_dir.mkdir()
            (prompts_dir / "stale.prompt.md").write_text("old", encoding="utf-8")
            template = base / "template.md.j2"
            template.write_text("{{ meeting.title }}\n{{ transcript }}", encoding="utf-8")

            options = mod.PromptsOptions(
                run=base,
                template=template,
                encoding="o200k_base",
                max_prompt_tiktoken_count=100000,
                format=mod.OutputFormat.json,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mod.build_prompts(options), 0)
            self.assertFalse((prompts_dir / "stale.prompt.md").exists())
            index = json.loads((base / "prompt-index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["counts"]["prompts"], 1)
            self.assertEqual(index["prompts"][0]["minute_token"], "obc1")
            self.assertEqual(index["prompts"][0]["prompt_path"], "prompts/obc1.prompt.md")
            self.assertNotIn("path", index["prompts"][0])

    def test_prompts_missing_transcript_removes_stale_index_and_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "selected.txt").write_text("missing\n", encoding="utf-8")
            (base / "prompt-index.json").write_text('{"ok": true}\n', encoding="utf-8")
            prompts_dir = base / "prompts"
            prompts_dir.mkdir()
            stale_prompt = prompts_dir / "stale.prompt.md"
            stale_prompt.write_text("old", encoding="utf-8")
            template = base / "template.md.j2"
            template.write_text("{{ transcript }}", encoding="utf-8")

            options = mod.PromptsOptions(run=base, template=template)
            with self.assertRaises(SystemExit):
                mod.build_prompts(options)
            self.assertFalse((base / "prompt-index.json").exists())
            self.assertFalse(stale_prompt.exists())

    def test_cli_prompts_missing_transcript_json_error_is_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "selected.txt").write_text("missing\n", encoding="utf-8")
            prompts_dir = base / "prompts"
            prompts_dir.mkdir()
            (prompts_dir / "stale.prompt.md").write_text("old", encoding="utf-8")
            template = base / "template.md.j2"
            template.write_text("{{ transcript }}", encoding="utf-8")

            result = run_cli(
                [
                    "prompts",
                    "--run",
                    str(base),
                    "--template",
                    str(template),
                    "--format",
                    "json",
                ],
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("missing", payload["error"])
            self.assertEqual(result.stderr, "")
            self.assertFalse((prompts_dir / "stale.prompt.md").exists())

    def test_cli_check_json_stdout_is_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            minute_dir = base / "minutes" / "obc1"
            minute_dir.mkdir(parents=True)
            (minute_dir / "transcript.txt").write_text("说话人 00:00\n内容", encoding="utf-8")
            (minute_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "minute_token": "obc1",
                        "title": "测试会议",
                        "sha256": "a",
                        "prefix_sha256": "b",
                        "first_line": "说话人 00:00",
                        "line_count": 2,
                        "transcript_tiktoken_count": 10,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            (base / "pulled.json").write_text(
                json.dumps({"ok": True, "counts": {"pulled": 1, "failed": 0}, "pulled": ["obc1"]}),
                encoding="utf-8",
            )
            result = run_cli(["check", "--run", str(base), "--format", "json"])
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["counts"]["pulled"], 1)

    def test_cli_check_without_pull_json_fails_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result = run_cli(["check", "--run", str(base), "--format", "json"])
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("pulled.json", payload["error"])

    def test_pull_uses_relative_output_dir_for_lark_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "minutes-found.json").write_text(
                json.dumps({"minutes": [{"minute_token": "obc1", "title": "测试会议"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            seen_output_dirs: list[str] = []

            def fake_run_json(cmd, *, cwd, log, require_ok=True):
                output_dir = cmd[cmd.index("--output-dir") + 1]
                seen_output_dirs.append(output_dir)
                self.assertFalse(Path(output_dir).is_absolute())
                transcript = Path(cwd) / output_dir / "obc1.txt"
                transcript.parent.mkdir(parents=True, exist_ok=True)
                transcript.write_text("说话人 00:00\n内容", encoding="utf-8")
                return {
                    "ok": True,
                    "data": {
                        "notes": [
                            {
                                "minute_token": "obc1",
                                "title": "测试会议",
                                "artifacts": {"transcript_file": str(transcript.relative_to(cwd))},
                            }
                        ]
                    },
                }

            original_require_commands = mod.require_commands
            original_run_json = mod.run_json
            patch_module_attr("require_commands", lambda command_names: None)
            patch_module_attr("run_json", fake_run_json)
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    exit_code = mod.pull_minutes(mod.PullOptions(run=base, format=mod.OutputFormat.json))
                self.assertEqual(exit_code, 0)
                self.assertEqual(seen_output_dirs, ["raw/pull-output/batch-001"])
                self.assertTrue((base / "minutes" / "obc1" / "transcript.txt").exists())
                self.assertFalse((base / "raw" / "pull-output").exists())
                pulled = json.loads((base / "pulled.json").read_text(encoding="utf-8"))
                self.assertTrue(pulled["ok"])
            finally:
                patch_module_attr("require_commands", original_require_commands)
                patch_module_attr("run_json", original_run_json)

    def test_run_command_nonzero_return_keeps_single_json_report(self) -> None:
        output = io.StringIO()

        def action() -> int:
            mod.emit({"ok": False, "counts": {"failed": 1}}, fmt=mod.OutputFormat.json)
            return 1

        with contextlib.redirect_stdout(output), self.assertRaises(mod.typer.Exit) as raised:
            mod.run_command(action, fmt=mod.OutputFormat.json)
        self.assertEqual(raised.exception.exit_code, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])

    def test_summarize_rejects_prompt_index_with_oversized_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "prompt-index.json").write_text(
                json.dumps({"ok": False, "prompts": [], "oversized": [{"minute_token": "obc1"}]}),
                encoding="utf-8",
            )
            original_require_commands = mod.require_commands
            patch_module_attr("require_commands", lambda command_names: None)
            try:
                with self.assertRaises(SystemExit) as raised:
                    mod.summarize_prompts(mod.SummarizeOptions(run=base))
                self.assertIn("ok=false", str(raised.exception))
                index = json.loads((base / "summaries" / "index.json").read_text(encoding="utf-8"))
                self.assertFalse(index["ok"])
                self.assertIn("prompt-index.json ok=false", index["error"])
            finally:
                patch_module_attr("require_commands", original_require_commands)

    @staticmethod
    def meta(
        minute_token: str,
        title: str,
        *,
        sha: str,
        prefix: str,
        first: str,
        lines: int,
    ) -> dict:
        return {
            "minute_token": minute_token,
            "title": title,
            "sha256": sha,
            "prefix_sha256": prefix,
            "first_line": first,
            "line_count": lines,
            "transcript_tiktoken_count": lines * 10,
            "sources": ["minutes_owner_search"],
            "rel_transcript_path": f"minutes/{minute_token}/transcript.txt",
        }


if __name__ == "__main__":
    unittest.main()
