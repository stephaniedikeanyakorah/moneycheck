"""Tests for MoneyCheck (text version). Standard library only:

    python -m unittest discover tests -v

Each test drives a real Session with scripted keyboard input and checks what is printed and logged.
"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from moneycheck import Session, load_scenarios  # noqa: E402

SCENARIOS = load_scenarios()
ORDER = [s["id"] for s in SCENARIOS]
WRONG = {"lisa", "overdraft", "credit-score"}


def run(inputs, mode="linked", nudge=True, answer_key=False, color=False, delay=0, scenarios=SCENARIOS):
    """Run a session with scripted input. Returns (printed text, log rows, session)."""
    feed, printed = iter([""] + inputs), []   # "" = press Enter at the intro
    tmp = tempfile.mkdtemp()

    def fake_input(prompt=""):
        printed.append(prompt)
        return next(feed)                       # StopIteration if a test runs out of input

    s = Session(scenarios, mode=mode, nudge=nudge, answer_key=answer_key, color=color, delay=delay,
                input_fn=fake_input, out=lambda *a: printed.append(" ".join(map(str, a))), log_dir=tmp)
    s.run()
    return "\n".join(printed), s.log, s


class DataChecks(unittest.TestCase):
    """scenarios.json is the contract between the simulated AI and the interface."""

    def test_counts(self):
        self.assertEqual(len(SCENARIOS), 9)
        self.assertEqual(len(set(ORDER)), 9, "scenario ids are unique")
        self.assertEqual({s["id"] for s in SCENARIOS if not s["aiCorrect"]}, WRONG)
        self.assertEqual(sum(bool(s.get("declined")) for s in SCENARIOS), 1)

    def test_every_scenario_is_consistent(self):
        for sc in SCENARIOS:
            with self.subTest(sc["id"]):
                used = [p["c"] for p in sc["parts"] if not isinstance(p, str)]
                self.assertEqual(sorted(used), sorted(c["id"] for c in sc["claims"]), "each claim appears once")
                self.assertEqual(sum(c["key"] for c in sc["claims"]), 1, "exactly one key claim")
                for c in sc["claims"]:
                    src = sc["sources"][c["source"]]
                    self.assertIn(src["reliability"], ("official", "guide", "forum"))
                    self.assertTrue(src["checked"])
                    self.assertIn("<mark>", src["excerpt"])

    def test_wrong_answers_are_catchable_from_what_is_shown(self):
        for sc in SCENARIOS:
            key = next(c for c in sc["claims"] if c["key"])
            forum = sc["sources"][key["source"]]["reliability"] == "forum"
            with self.subTest(sc["id"]):
                if sc["aiCorrect"]:
                    self.assertTrue(all(c["matches"] for c in sc["claims"]) and not forum)
                else:
                    self.assertTrue(not key["matches"] or forum)


class Modes(unittest.TestCase):
    """All three modes come from the same data and differ only in presentation."""

    def test_each_mode_renders_and_logs(self):
        for mode in ("none", "standard", "linked"):
            with self.subTest(mode):
                text, log, _ = run(["r"] * 9, mode=mode)
                self.assertEqual(len(log), 9)
                self.assertTrue(all(r["mode"] == mode for r in log))
                self.assertEqual(("[1]" in text), mode == "linked", "claim tags only in source-linked mode")
                self.assertEqual(("Sources\n" in text), mode == "linked", "source list only in source-linked mode")
                # The answer body appears in B and C but not A.
                flat = " ".join(text.split())   # ignore line wrapping
                self.assertEqual(("government adds a 25% bonus" in flat), mode != "none")
                expected = ["appropriate" if i in WRONG else "under-reliance" for i in ORDER]
                self.assertEqual([r["outcome"] for r in log], expected)

    def test_checking_is_refused_outside_source_linked_mode(self):
        text, log, _ = run(["2", "r"] + ["r"] * 8, mode="standard")
        self.assertIn("Sources aren't shown in this mode.", text)
        self.assertEqual(log[0]["sourcesOpened"], 0)


class SourceLinking(unittest.TestCase):
    def test_checking_lisa_claim_shows_the_contradiction(self):
        text, log, _ = run(["3", "r"] + ["r"] * 8)
        self.assertIn("you only\n  │ lose 10%", text)
        self.assertIn("«25%\n  │ withdrawal charge»", text)
        self.assertIn("Last checked: Nov 2026", text)
        self.assertTrue(log[0]["keyChecked"])

    def test_forum_source_is_labelled(self):
        text, _, _ = run(["r"] * 9)
        self.assertIn("[! Unverified forum post] Forum post (made up for this prototype)", text)

    def test_decline_case(self):
        text, log, _ = run(["r"] * 9)
        self.assertIn("! None of my sources mention this app", text)
        self.assertIn("No source answers the main question.", text)
        self.assertTrue(log[-1]["declined"])

    def test_report(self):
        text, log, _ = run(["report 3", "r"] + ["r"] * 8)
        self.assertIn("Flagged claim [3] for review", text)
        self.assertEqual(log[0]["reported"], "3")


class Nudge(unittest.TestCase):
    def test_nudge_when_key_claim_unchecked_then_check(self):
        text, log, _ = run(["f", "c", "r"] + ["r"] * 8)
        self.assertIn("Quick check? This advice depends on claim [3]", text)
        self.assertEqual((log[0]["nudgeShown"], log[0]["nudgeResponse"], log[0]["keyChecked"]), (True, "checked", True))
        self.assertEqual(log[0]["decision"], "reject")

    def test_nudge_skip_counts_as_following(self):
        _, log, _ = run(["f", "f"] + ["r"] * 8)
        self.assertEqual((log[0]["nudgeResponse"], log[0]["outcome"]), ("skipped", "over-reliance"))

    def test_no_nudge_once_key_claim_checked(self):
        text, log, _ = run(["3", "f"] + ["r"] * 8)
        self.assertNotIn("Quick check?", text)
        self.assertFalse(log[0]["nudgeShown"])

    def test_nudge_can_be_turned_off(self):
        text, log, _ = run(["f"] + ["r"] * 8, nudge=False)
        self.assertNotIn("Quick check?", text)
        self.assertEqual(log[0]["outcome"], "over-reliance")

    def test_no_nudge_in_other_modes(self):
        text, _, _ = run(["f"] * 9, mode="standard")
        self.assertNotIn("Quick check?", text)


class Conversation(unittest.TestCase):
    def test_repair_on_unrecognised_input(self):
        text, log, _ = run(["what", "7", "r"] + ["r"] * 8)
        self.assertIn("Sorry, I didn't understand that.", text)
        self.assertIn("There's no claim [7] here. Claims are 1, 2, 3.", text)
        self.assertEqual(log[0]["invalidInputs"], 1)

    def test_help_lists_commands(self):
        text, _, _ = run(["h", "r"] + ["r"] * 8)
        self.assertIn("report 2    flag claim 2's source", text)

    def test_typing_indicator_before_answer(self):
        text, _, _ = run(["r"], scenarios=SCENARIOS[:1], delay=0.01)
        self.assertLess(text.index("MoneyCheck AI is typing"), text.index("Yes. Put all your savings"))

    def test_quitting_early_keeps_what_was_answered(self):
        text, log, _ = run(["r", "q"])
        self.assertEqual(len(log), 1)
        self.assertIn("Session ended early.", text)

    def test_plain_text_mode_has_no_colour_codes(self):
        plain, _, _ = run(["3", "r"], scenarios=SCENARIOS[:1])
        coloured, _, _ = run(["3", "r"], scenarios=SCENARIOS[:1], color=True)
        self.assertNotIn("\033[", plain)
        self.assertIn("\033[30;43m25%", coloured)
        self.assertNotIn("\033[30;43m  │", coloured, "highlight never covers the margin")


class Scoring(unittest.TestCase):
    def test_full_scripted_run(self):
        inputs = [
            "f", "c", "r",          # 1 LISA (wrong): nudge -> check -> reject      = appropriate
            "f", "f",               # 2 student loan (right): skip nudge, follow     = appropriate
            "2", "f",               # 3 BNPL (right): check first, follow, no nudge  = appropriate
            "2", "f",               # 4 overdraft (wrong, forum): follow anyway      = over-reliance
            "f", "f",               # 5 ISA (right)                                  = appropriate
            "f", "f",               # 6 credit score (wrong)                         = over-reliance
            "r",                    # 7 tax refund (right): reject                   = under-reliance
            "f", "f",               # 8 council tax (right)                          = appropriate
            "f", "f",               # 9 crypto (declines, right)                     = appropriate
        ]
        text, log, s = run(inputs)
        self.assertEqual([r["outcome"] for r in log], ["appropriate", "appropriate", "appropriate", "over-reliance",
                                                      "appropriate", "over-reliance", "under-reliance",
                                                      "appropriate", "appropriate"])
        self.assertIn("Appropriate reliance          6/9", text)
        self.assertIn("Wrong advice followed         2/3", text)
        self.assertIn("Good advice rejected          1/6", text)
        self.assertTrue(all(r["seconds"] >= 0 for r in log))

        files = list(Path(s.log_dir).glob("session-*-linked.csv"))
        self.assertEqual(len(files), 1)
        with open(files[0], newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[3]["outcome"], "over-reliance")


if __name__ == "__main__":
    unittest.main()
