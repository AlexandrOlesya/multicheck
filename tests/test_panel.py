import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from multicheck import cli, context, convergence, panel, prompts


def fake_opener(payloads):
    """Отдаёт заготовленные ответы по очереди; строка 'boom' — исключение."""
    queue = list(payloads)

    def opener(request, timeout=None):
        if not queue:
            raise AssertionError("лишний вызов сети")
        item = queue.pop(0)
        if item == "boom":
            raise OSError("сеть отвалилась")
        return io.BytesIO(json.dumps(item).encode())

    return opener


def reply(text):
    return {"choices": [{"message": {"content": text}}]}


class KeyResolution(unittest.TestCase):
    def test_env_wins(self):
        self.assertEqual(panel.resolve_key({"OPENROUTER_API_KEY": "from-env"}, files=[]), "from-env")

    def test_falls_back_to_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".key", delete=False) as handle:
            handle.write("  from-file\n")
        self.assertEqual(panel.resolve_key({}, files=[handle.name]), "from-file")
        os.unlink(handle.name)

    def test_blank_env_is_ignored(self):
        with tempfile.NamedTemporaryFile("w", suffix=".key", delete=False) as handle:
            handle.write("from-file")
        self.assertEqual(
            panel.resolve_key({"OPENROUTER_API_KEY": "   "}, files=[handle.name]), "from-file"
        )
        os.unlink(handle.name)

    def test_missing_key_explains_itself(self):
        with self.assertRaises(panel.MissingKey) as ctx:
            panel.resolve_key({}, files=["/nope/does-not-exist"])
        self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))

    def test_import_does_not_need_key(self):
        """Ключ читается по требованию, а не при импорте — иначе модуль не
        импортируется на чужой машине и тесты вообще не запускаются."""
        self.assertTrue(hasattr(panel, "resolve_key"))


class Ask(unittest.TestCase):
    def test_returns_content(self):
        got, cost = panel.ask("m", "sys", "diff", "k", opener=fake_opener([reply("нашёл дыру")]))
        self.assertEqual(got, "нашёл дыру")
        self.assertEqual(cost, 0.0, "в ответе без usage стоимость считается нулевой")

    def test_retries_after_network_error(self):
        got, _ = panel.ask("m", "sys", "diff", "k", opener=fake_opener(["boom", reply("со второго раза")]))
        self.assertEqual(got, "со второго раза")

    def test_empty_content_is_not_an_answer(self):
        got, _ = panel.ask("m", "sys", "diff", "k", retries=0, opener=fake_opener([reply("   ")]))
        self.assertIsNone(got)

    def test_gives_up_after_retries(self):
        got, _ = panel.ask("m", "sys", "diff", "k", retries=1, opener=fake_opener(["boom", "boom"]))
        self.assertIsNone(got)

    def test_missing_choices_does_not_crash(self):
        got, _ = panel.ask("m", "sys", "diff", "k", retries=0, opener=fake_opener([{"error": "rate limit"}]))
        self.assertIsNone(got)

    def test_long_input_is_truncated(self):
        seen = {}

        def opener(request, timeout=None):
            seen["len"] = len(json.loads(request.data)["messages"][1]["content"])
            return io.BytesIO(json.dumps(reply("ok")).encode())

        panel.ask("m", "sys", "x" * (panel.MAX_INPUT_CHARS + 5000), "k", opener=opener)
        self.assertEqual(seen["len"], panel.MAX_INPUT_CHARS)


class Defaults(unittest.TestCase):
    def test_run_falls_back_to_configured_panel_and_key(self):
        """Без явных models/key берётся панель из окружения и найденный ключ —
        мутация `models or panel_models()` в `and` не должна проходить молча."""
        saved = dict(os.environ)
        os.environ["MC_PANEL"] = "x/alpha,y/beta"
        os.environ["OPENROUTER_API_KEY"] = "k"
        try:
            results = panel.run("sys", "payload", opener=fake_opener([reply("a"), reply("b")]))
        finally:
            os.environ.clear()
            os.environ.update(saved)
        self.assertEqual([model for model, _, _ in results], ["x/alpha", "y/beta"])


class Render(unittest.TestCase):
    def test_marks_silent_models(self):
        out = panel.render([("a/one", "находка"), ("b/two", None)])
        self.assertIn("one", out)
        self.assertIn("не ответил", out)

    def test_reports_total_failure(self):
        out = panel.render([("a/one", None), ("b/two", None)])
        self.assertIn("ПАНЕЛЬ НЕДОСТУПНА", out)

    def test_success_does_not_claim_panel_is_down(self):
        out = panel.render([("a/one", "находка"), ("b/two", None)])
        self.assertNotIn("ПАНЕЛЬ НЕДОСТУПНА", out,
                         "если хоть кто-то ответил, паниковать нельзя")

    def test_shows_what_the_run_cost(self):
        """Цена прогона должна быть видна: иначе расход растёт незаметно."""
        out = panel.render([("a/one", "находка", 0.0123), ("b/two", None, 0.0004)])
        self.assertIn("$0.0127", out)

    def test_no_cost_line_when_nothing_billed(self):
        out = panel.render([("a/one", "находка", 0.0)])
        self.assertNotIn("прогон стоил", out)

    def test_cost_is_captured_from_response(self):
        answer = {"choices": [{"message": {"content": "есть"}}], "usage": {"cost": 0.042}}
        got, cost = panel.ask("m", "sys", "diff", "k", opener=fake_opener([answer]))
        self.assertEqual(got, "есть")
        self.assertEqual(cost, 0.042)

    def test_uses_short_model_name(self):
        out = panel.render([("vendor/family/model-x", "текст")])
        self.assertIn("model-x", out)
        self.assertNotIn("vendor/family", out)


class Payload(unittest.TestCase):
    def test_reads_file_argument(self):
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as handle:
            handle.write("содержимое дифа")
        self.assertEqual(panel.read_payload(["prog", handle.name]), "содержимое дифа")
        os.unlink(handle.name)

    def test_reads_stdin_when_dash(self):
        self.assertEqual(panel.read_payload(["prog", "-"], io.StringIO("из потока")), "из потока")

    def test_reads_stdin_without_args(self):
        self.assertEqual(panel.read_payload(["prog"], io.StringIO("из потока")), "из потока")

    def test_binary_file_does_not_crash(self):
        """Диф может содержать бинарь — нечитаемые байты не должны ронять прогон."""
        with tempfile.NamedTemporaryFile("wb", suffix=".diff", delete=False) as handle:
            handle.write(b"diff --git a/logo.png\n\xff\xfe\x00binary\n")
        got = panel.read_payload(["prog", handle.name])
        self.assertIn("diff --git", got)
        os.unlink(handle.name)


class Context(unittest.TestCase):
    DIFF = (
        "diff --git a/app/a.rb b/app/a.rb\n--- a/app/a.rb\n+++ b/app/a.rb\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/lib/b.py b/lib/b.py\n--- /dev/null\n+++ b/lib/b.py\n@@ -0,0 +1 @@\n+z\n"
    )

    def test_finds_changed_files(self):
        self.assertEqual(context.changed_files(self.DIFF), ["app/a.rb", "lib/b.py"])

    def test_ignores_deleted_files(self):
        deleted = "--- a/gone.rb\n+++ /dev/null\n"
        self.assertEqual(context.changed_files(deleted), [])

    def test_collects_existing_files_only(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "app"))
        with open(os.path.join(root, "app", "a.rb"), "w", encoding="utf-8") as handle:
            handle.write("class A; end")
        collected = context.collect(self.DIFF, root)
        self.assertIn("class A; end", collected)
        self.assertIn("FILE: app/a.rb", collected)
        self.assertNotIn("lib/b.py", collected, "несуществующий файл не должен попадать")

    def test_missing_root_is_survivable(self):
        self.assertEqual(context.collect(self.DIFF, "/nope/missing"), "")
        self.assertEqual(context.collect(self.DIFF, ""), "")

    def test_budget_is_respected(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "app"))
        with open(os.path.join(root, "app", "a.rb"), "w", encoding="utf-8") as handle:
            handle.write("x" * 5000)
        collected = context.collect(self.DIFF, root, budget=1000)
        self.assertLess(len(collected), 1200)
        self.assertIn("не поместились", collected)

    def test_context_goes_before_diff(self):
        merged = context.with_context("THE DIFF", "--- FILE: a.rb ---\ncode")
        self.assertLess(merged.index("=== FILES ==="), merged.index("THE DIFF"))
        self.assertIn("=== DIFF ===", merged)

    def test_no_context_changes_nothing(self):
        self.assertEqual(context.with_context("DIFF", ""), "DIFF")
        self.assertEqual(context.with_context("DIFF", "   "), "DIFF")

    def test_context_can_be_switched_off(self):
        """Контекст кратно дороже — в хуке он должен выключаться, иначе каждый
        пуш стоит в разы больше."""
        self.assertFalse(cli.context_wanted({"MC_NO_CONTEXT": "1"}))
        self.assertTrue(cli.context_wanted({"MC_NO_CONTEXT": "0"}))
        self.assertTrue(cli.context_wanted({}))

    def test_repo_root_from_flag_and_env(self):
        self.assertEqual(cli.context_root(["mc", "--repo", "/tmp/x"], {}), "/tmp/x")
        self.assertEqual(cli.context_root(["mc"], {"MC_REPO": "/tmp/y"}), "/tmp/y")


class ContextIsAttachedOnlyWhereItPays(unittest.TestCase):
    """Контекст файлов дорог. Он должен попадать только в разбор кода и только
    когда его не выключили: иначе допрос и опровержение стоят как ревью."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "app"))
        with open(os.path.join(self.root, "app", "a.rb"), "w", encoding="utf-8") as handle:
            handle.write("class Payment; end")
        self.diff = "--- a/app/a.rb\n+++ b/app/a.rb\n@@ -1 +1 @@\n-x\n+y\n"
        self.dump = os.path.join(tempfile.mkdtemp(), "payload.txt")
        self.saved = dict(os.environ)
        os.environ["OPENROUTER_API_KEY"] = "k"
        os.environ["MC_PANEL"] = "a/one"
        os.environ["MC_REPO"] = self.root
        os.environ["MC_DUMP_PAYLOAD"] = self.dump

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def sent(self, mode):
        cli.main(mode, ["prog", "-"], stdin=io.StringIO(self.diff),
                 opener=fake_opener([reply("ok")]))
        with open(self.dump, encoding="utf-8") as handle:
            return handle.read()

    def test_review_gets_file_contents(self):
        self.assertIn("class Payment; end", self.sent("review"))

    def test_grill_does_not_pay_for_context(self):
        self.assertNotIn("class Payment; end", self.sent("grill"))

    def test_refute_does_not_pay_for_context(self):
        self.assertNotIn("class Payment; end", self.sent("refute"))

    def test_switch_off_works_for_review(self):
        os.environ["MC_NO_CONTEXT"] = "1"
        self.assertNotIn("class Payment; end", self.sent("review"))


class Convergence(unittest.TestCase):
    def test_no_findings_is_ideal(self):
        state, _ = convergence.decide([], [])
        self.assertEqual(state, convergence.IDEAL)

    def test_shrinking_findings_continue(self):
        history = [convergence.signature([{"file": "a", "issue": "x"}, {"file": "b", "issue": "y"}])]
        state, _ = convergence.decide(history, [{"file": "a", "issue": "x"}])
        self.assertEqual(state, convergence.CONTINUE)

    def test_same_findings_twice_is_looping(self):
        findings = [{"file": "a", "issue": "x"}]
        state, why = convergence.decide([convergence.signature(findings)], findings)
        self.assertEqual(state, convergence.LOOPING)
        self.assertIn("редизайн", why)

    def test_count_not_falling_is_looping(self):
        history = [convergence.signature([{"file": "a", "issue": "x"}])]
        state, _ = convergence.decide(history, [{"file": "b", "issue": "y"}])
        self.assertEqual(state, convergence.LOOPING)

    def test_signature_ignores_order_and_case(self):
        one = convergence.signature([{"file": "A", "issue": "X"}, {"file": "b", "issue": "y"}])
        two = convergence.signature([{"file": "b", "issue": "Y"}, {"file": "a", "issue": "x"}])
        self.assertEqual(one, two)

    def test_backstop_stops_endless_shrinking(self):
        history = [convergence.signature([{"file": str(i), "issue": "x"}]) for i in range(4)]
        state, why = convergence.decide(history, [], max_rounds=5)
        self.assertEqual(state, convergence.IDEAL)
        history = [convergence.signature([{"file": str(i), "issue": "x"} for i in range(n)]) for n in (9, 8, 7, 6)]
        state, why = convergence.decide(history, [{"file": str(i), "issue": "x"} for i in range(5)], max_rounds=5)
        self.assertEqual(state, convergence.BACKSTOP)
        self.assertIn("лимит", why)


class Modes(unittest.TestCase):
    def test_grill_fast_uses_one_model(self):
        env = {"MC_PANEL": "a/one,b/two,c/three", "GRILL_FAST": "1"}
        self.assertEqual(len(cli.models_for("grill", env)), 1)

    def test_review_uses_whole_panel(self):
        env = {"MC_PANEL": "a/one,b/two,c/three"}
        self.assertEqual(len(cli.models_for("review", env)), 3)

    def test_grill_without_fast_uses_whole_panel(self):
        env = {"MC_PANEL": "a/one,b/two,c/three"}
        self.assertEqual(len(cli.models_for("grill", env)), 3, "урезать панель должен только GRILL_FAST")

    def test_fast_flag_does_not_shrink_other_modes(self):
        env = {"MC_PANEL": "a/one,b/two,c/three", "GRILL_FAST": "1"}
        self.assertEqual(len(cli.models_for("review", env)), 3)
        self.assertEqual(len(cli.models_for("refute", env)), 3)

    def test_panel_list_tolerates_spaces(self):
        self.assertEqual(panel.panel_models({"MC_PANEL": "  a/one , b/two  "}), ["a/one", "b/two"])

    def test_panel_is_configurable(self):
        self.assertEqual(panel.panel_models({"MC_PANEL": "x/y"}), ["x/y"])

    def test_default_panel_is_one_strong_model(self):
        """Замер показал: одна сильная модель находит втрое больше настоящих
        дефектов и выдаёт вдвое меньше мусора, чем три дешёвые вместе."""
        self.assertEqual(len(panel.DEFAULT_PANEL), 1)

    def test_cheap_panel_available_by_name(self):
        self.assertEqual(panel.panel_models({"MC_PANEL": "cheap"}), panel.CHEAP_PANEL)
        self.assertGreater(len(panel.CHEAP_PANEL), 1)

    def test_project_rules_appended(self):
        merged = prompts.with_project_rules("BASE", "никаких голых SQL")
        self.assertIn("BASE", merged)
        self.assertIn("никаких голых SQL", merged)

    def test_empty_project_rules_change_nothing(self):
        self.assertEqual(prompts.with_project_rules("BASE", "  "), "BASE")

    def test_example_rules_file_is_shipped_and_loads(self):
        """Пример должен лежать в репозитории и подставляться — иначе про
        MC_PROJECT_RULES никто не догадается."""
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        example = os.path.join(root, "examples", "project-rules.example.md")
        self.assertTrue(os.path.exists(example), "пример правил потерялся из репозитория")
        with open(example, encoding="utf-8") as handle:
            text = handle.read()
        merged = prompts.with_project_rules("BASE", text)
        self.assertIn("BASE", merged)
        self.assertIn(text.strip(), merged)

    def test_project_rules_read_from_env_path(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as handle:
            handle.write("не трогай продовую очередь")
        missing = os.path.join(tempfile.mkdtemp(), "нет-такого.md")
        try:
            self.assertIn("продовую", cli.project_rules({"MC_PROJECT_RULES": handle.name}))
            self.assertEqual(cli.project_rules({"MC_PROJECT_RULES": missing}), "")
            self.assertEqual(cli.project_rules({}), "")
        finally:
            os.unlink(handle.name)

    def test_static_findings_are_marked_as_already_known(self):
        merged = cli.with_static("DIFF HERE", "app.rb:12 Style/Foo")
        self.assertIn("DIFF HERE", merged)
        self.assertIn("app.rb:12", merged)
        self.assertIn("Do NOT repeat", merged)
        self.assertIn("=== ALREADY REPORTED ===", merged)
        self.assertIn("=== END ===", merged)
        self.assertLess(merged.index("ALREADY REPORTED"), merged.index("DIFF HERE"),
                        "уже найденное должно идти до дифа, иначе модель его не заметит")

    def test_no_static_output_changes_nothing(self):
        self.assertEqual(cli.with_static("DIFF", ""), "DIFF")
        self.assertEqual(cli.with_static("DIFF", "   "), "DIFF")

    def test_static_findings_read_from_env_path(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write("lib/a.rb:3 unused variable")
        try:
            self.assertIn("unused variable", cli.static_findings({"MC_STATIC": handle.name}))
            self.assertEqual(cli.static_findings({"MC_STATIC": "/nope/missing.txt"}), "")
            self.assertEqual(cli.static_findings({}), "")
        finally:
            os.unlink(handle.name)

    def test_directory_as_rules_path_is_survivable(self):
        """Путь может указывать на папку — прогон не должен падать."""
        self.assertEqual(cli.project_rules({"MC_PROJECT_RULES": tempfile.mkdtemp()}), "")

    def test_huge_rules_file_is_capped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as handle:
            handle.write("я" * (cli.MAX_RULES_CHARS + 5000))
        try:
            self.assertEqual(len(cli.project_rules({"MC_PROJECT_RULES": handle.name})), cli.MAX_RULES_CHARS)
        finally:
            os.unlink(handle.name)

    def test_prompts_stay_generic(self):
        """Промты не должны нести деталей конкретного проекта: они публичные,
        а внутреннее подставляется через MC_PROJECT_RULES. Свой список слов
        можно задать в MC_FORBIDDEN_WORDS."""
        blob = " ".join([prompts.BREAK, prompts.REFUTE, prompts.GRILL]).lower()
        extra = os.environ.get("MC_FORBIDDEN_WORDS", "")
        words = ["internal", "confidential"] + [w.strip().lower() for w in extra.split(",") if w.strip()]
        for leak in words:
            self.assertNotIn(leak, blob, f"в промт просочилась деталь проекта: {leak}")


class CliBehaviour(unittest.TestCase):
    def test_empty_input_exits_clean(self):
        code = cli.main("review", ["prog", "-"], stdin=io.StringIO("   "))
        self.assertEqual(code, 0)

    def test_missing_key_exits_with_code_two(self):
        saved = dict(os.environ)
        os.environ.pop("OPENROUTER_API_KEY", None)
        panel.KEY_FILES, kept = ["/nope/missing"], panel.KEY_FILES
        try:
            code = cli.main("review", ["prog", "-"], stdin=io.StringIO("diff"))
        finally:
            panel.KEY_FILES = kept
            os.environ.clear()
            os.environ.update(saved)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
