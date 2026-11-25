#!/usr/bin/env python3
"""MoneyCheck: a text-based prototype of source-linked AI money advice.

The AI is simulated: answers, claims and sources come from scenarios.json, so the
researcher controls exactly when the AI is wrong. Run it in a terminal:

    python moneycheck.py                  # source-linked mode (C)
    python moneycheck.py --mode standard  # standard LLM-style explanation (B)
    python moneycheck.py --mode none      # recommendation only (A)

Python 3.8+, standard library only. No API key needed.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIDTH = 78
MODES = {"none": "A: no explanation", "standard": "B: standard explanation", "linked": "C: source-linked"}
LOG_FIELDS = ["scenario", "mode", "aiCorrect", "decision", "appropriate", "outcome", "sourcesOpened",
              "keyChecked", "reported", "declined", "nudgeShown", "nudgeResponse", "invalidInputs", "seconds"]


# ---------------------------------------------------------------- styling
class Style:
    """ANSI colours, or plain text markers when colour is off (e.g. when logs are piped)."""
    CODES = {"bold": "1", "dim": "2", "green": "32", "red": "31", "blue": "34", "yellow": "33",
             "cyan": "36", "hl": "30;43", "brand": "1;97;42"}

    def __init__(self, color=True):
        self.color = color

    def __call__(self, text, *names):
        if not self.color or not names:
            return text
        return "\033[" + ";".join(self.CODES[n] for n in names) + "m" + text + "\033[0m"

    def highlight(self, text):
        """Colour the «marked» words. Applied after wrapping, line by line, so a highlight
        that crosses a line break never bleeds into the next line's margin."""
        if not self.color:
            return text
        out, inside = [], False
        for line in text.split("\n"):
            margin = re.match(r"\s*(│ )?", line).group(0)
            body = line[len(margin):]
            pieces, buf = [], ""
            for ch in body:
                if ch in "«»":
                    if buf:
                        pieces.append(self(buf, "hl") if inside else buf)
                    buf, inside = "", ch == "«"
                else:
                    buf += ch
            if buf:
                pieces.append(self(buf, "hl") if inside else buf)
            out.append(margin + "".join(pieces))
        return "\n".join(out)


def marked(excerpt):
    """Turn the source's <mark>…</mark> into «…» so wrapping can see the words."""
    return re.sub(r"<mark>(.*?)</mark>", r"«\1»", excerpt)


RELIABILITY = {
    "official": ("✓ Official source", "green"),
    "guide": ("Company guide", "blue"),
    "forum": ("! Unverified forum post", "red"),
}


def wrap(text, indent=""):
    return "\n".join(textwrap.wrap(text, WIDTH, initial_indent=indent, subsequent_indent=indent)) or indent


# ---------------------------------------------------------------- one question
class Trial:
    """Interaction state for one question: what was opened, reported and decided."""

    def __init__(self, scenario):
        self.sc = scenario
        self.opened = set()        # claims whose source the person opened
        self.reported = set()      # claims flagged with "report"
        self.nudge_shown = False
        self.nudge_response = ""
        self.invalid = 0           # unrecognised inputs (a rough measure of confusion)
        self.start = None

    @property
    def key(self):
        return next(c for c in self.sc["claims"] if c["key"])


class Session:
    def __init__(self, scenarios, mode="linked", nudge=True, answer_key=False, color=True,
                 delay=1.0, input_fn=input, out=print, log_dir=None):
        self.scenarios, self.mode, self.nudge, self.answer_key = scenarios, mode, nudge, answer_key
        self.s = Style(color)
        self.delay, self.input, self.out = delay, input_fn, out
        self.log_dir = Path(log_dir) if log_dir else HERE / "logs"
        self.log = []

    # ---------- rendering
    def answer(self, sc):
        """All three modes are built from the same parts, so they differ only in presentation."""
        if self.mode == "none":
            return ""
        out = []
        for p in sc["parts"]:
            if isinstance(p, str):
                out.append(p)
            else:
                c = next(x for x in sc["claims"] if x["id"] == p["c"])
                out.append(c["text"] + (f" [{c['id']}]" if self.mode == "linked" else ""))
        return "".join(out)

    def label(self, source):
        text, colour = RELIABILITY[source["reliability"]]
        return self.s("[" + text + "]", colour)

    def show_question(self, n, sc):
        s = self.s
        self.out("")
        self.out(s(f"── Question {n} of {len(self.scenarios)} " + "─" * (WIDTH - 20), "dim"))
        self.out(wrap("You: " + sc["question"]))
        self.out("")
        if self.delay:
            self.out(s("MoneyCheck AI is typing…", "dim"))
            time.sleep(self.delay)
        self.out(s("MoneyCheck AI", "bold", "green"))
        if sc.get("declined") and self.mode != "none":
            self.out(s(wrap("! " + sc["declineNote"]), "yellow"))
        self.out(s(wrap(sc["recommendation"]), "bold"))
        body = self.answer(sc)
        if body:
            self.out("")
            self.out(wrap(body))
        if self.mode == "linked":
            self.show_sources(sc)
        self.out(self.hint())

    def show_sources(self, sc):
        s = self.s
        self.out("")
        if sc.get("declined"):
            self.out(s(wrap("No source answers the main question. " + sc["closestMatch"]), "yellow"))
        self.out(s("Sources", "bold"))
        for c in sc["claims"]:
            src = sc["sources"][c["source"]]
            ticked = s(" (checked)", "dim") if c["id"] in self.trial.opened else ""
            self.out(f"  [{c['id']}] {self.label(src)} {src['name']}{ticked}")
            if c["key"]:
                self.out(s("      ↑ the advice depends on this claim", "yellow"))

    def hint(self):
        if self.mode == "linked":
            return self.s("\nType a claim number to check it · f = follow · r = don't follow · h = help", "cyan")
        return self.s("\nf = follow this advice · r = don't follow it · h = help", "cyan")

    def show_claim(self, cid):
        """Show the source beside the AI's claim: recognition, not recall."""
        sc, s = self.trial.sc, self.s
        c = next((x for x in sc["claims"] if x["id"] == cid), None)
        if c is None:
            ids = ", ".join(str(x["id"]) for x in sc["claims"])
            self.out(s(f"There's no claim [{cid}] here. Claims are {ids}.", "yellow"))
            return
        src = sc["sources"][c["source"]]
        self.trial.opened.add(cid)
        self.out("")
        self.out(s(f"  Claim [{cid}]", "bold") + ("  " + s("advice depends on this", "yellow") if c["key"] else ""))
        self.out(wrap("AI said: \"" + c["text"] + "\"", "  │ "))
        self.out(wrap(src["name"], "  │ ") + " " + self.label(src))
        self.out(self.s.highlight(wrap("Source says: " + marked(src["excerpt"]), "  │ ")))
        self.out(s(f"  │ Last checked: {src['checked']}" + (f" · {src['url']}" if src["url"] else " · no link available"), "dim"))
        self.out(s(f"  Type 'report {cid}' if this looks wrong.", "dim"))

    # ---------- the loop for one question
    def run_trial(self, n, sc):
        self.trial = t = Trial(sc)
        self.show_question(n, sc)
        t.start = time.monotonic()          # timing starts once the answer is on screen
        while True:
            raw = self.input(self.s("> ", "bold")).strip().lower()
            cmd, _, arg = raw.partition(" ")
            if raw.isdigit() or cmd in ("c", "check"):
                if self.mode != "linked":
                    self.out("Sources aren't shown in this mode.")
                    continue
                num = raw if raw.isdigit() else arg
                if not num.isdigit():
                    self.out("Which claim? For example: check 2")
                    continue
                self.show_claim(int(num))
            elif cmd in ("report", "flag") and self.mode == "linked":
                if arg.isdigit() and any(c["id"] == int(arg) for c in sc["claims"]):
                    t.reported.add(int(arg))
                    self.out(self.s(wrap(f"Flagged claim [{arg}] for review. Thanks. (Simulated: in the full "
                                         "system a person checks flagged sources.)"), "yellow"))
                else:
                    self.out("Which claim? For example: report 2")
            elif cmd in ("s", "sources") and self.mode == "linked":
                self.show_sources(sc)
            elif cmd in ("f", "follow"):
                if self.nudge_needed():
                    if self.ask_nudge():
                        continue          # they chose to check the claim first
                return self.decide("follow")
            elif cmd in ("r", "reject", "dont", "don't"):
                return self.decide("reject")
            elif cmd in ("h", "help", "?"):
                self.help()
            elif cmd in ("q", "quit", "exit"):
                raise KeyboardInterrupt
            else:
                # Repair turn: say what was not understood and what would work.
                t.invalid += 1
                self.out(self.s("Sorry, I didn't understand that." + self.hint(), "yellow"))

    def nudge_needed(self):
        t = self.trial
        return (self.mode == "linked" and self.nudge and t.key["id"] not in t.opened and not t.nudge_shown)

    def ask_nudge(self):
        """Soft nudge (mixed initiative: ask, don't force). Returns True if they chose to check."""
        t, k = self.trial, self.trial.key
        t.nudge_shown = True
        self.out(self.s(f"\nQuick check? This advice depends on claim [{k['id']}], which you haven't looked at.", "yellow"))
        while True:
            ans = self.input(self.s(f"  c = check claim [{k['id']}] · f = follow anyway > ", "bold")).strip().lower()
            if ans in ("c", "check", str(k["id"])):
                t.nudge_response = "checked"
                self.show_claim(k["id"])
                self.out(self.hint())
                return True
            if ans in ("f", "follow"):
                t.nudge_response = "skipped"
                return False
            t.invalid += 1
            self.out("Type c to check the claim or f to follow anyway.")

    def decide(self, decision):
        t, sc = self.trial, self.trial.sc
        followed = decision == "follow"
        if sc["aiCorrect"]:
            outcome = "appropriate" if followed else "under-reliance"
        else:
            outcome = "over-reliance" if followed else "appropriate"
        self.log.append({
            "scenario": sc["id"], "mode": self.mode, "aiCorrect": sc["aiCorrect"], "decision": decision,
            "appropriate": outcome == "appropriate", "outcome": outcome, "sourcesOpened": len(t.opened),
            "keyChecked": t.key["id"] in t.opened, "reported": " ".join(map(str, sorted(t.reported))) or "none",
            "declined": bool(sc.get("declined")), "nudgeShown": t.nudge_shown, "nudgeResponse": t.nudge_response,
            "invalidInputs": t.invalid, "seconds": round(time.monotonic() - t.start, 1),
        })
        self.out(self.s("Noted: you " + ("followed" if followed else "didn't follow") + " this advice.", "dim"))
        if self.answer_key:
            verdict = "right" if sc["aiCorrect"] else "wrong"
            self.out(self.s(wrap(f"Answer key: the AI was {verdict}. {sc['errorNote']}"),
                            "green" if sc["aiCorrect"] else "red"))
        return outcome

    def help(self):
        lines = ["Commands:"]
        if self.mode == "linked":
            lines += ["  1, 2, 3 …   check that claim against its source",
                      "  s           list the sources again",
                      "  report 2    flag claim 2's source as looking wrong"]
        lines += ["  f           follow this advice", "  r           don't follow it", "  q           quit"]
        self.out("\n".join(lines))

    # ---------- whole session
    def intro(self):
        s = self.s
        self.out(s("  £ MoneyCheck  ", "brand") + "  AI money advice you can check")
        self.out(s(f"  Mode {MODES[self.mode]} · simulated AI · not financial advice", "dim"))
        self.out("")
        self.out(wrap(f"You'll get {len(self.scenarios)} everyday money questions answered by an AI advisor. "
                      "For each one, decide whether you would follow its advice. Take as long as you like."))
        if self.mode == "linked":
            self.out(wrap("Each claim has a number in [brackets]. Type the number to see the source it came from."))
        self.input(s("\nPress Enter to start ", "bold"))

    def summary(self):
        s, n = self.s, len(self.log)
        if not n:
            return
        wrong = [r for r in self.log if not r["aiCorrect"]]
        right = n - len(wrong)
        appropriate = sum(r["appropriate"] for r in self.log)
        over = sum(r["outcome"] == "over-reliance" for r in self.log)
        under = sum(r["outcome"] == "under-reliance" for r in self.log)
        checked = sum(r["keyChecked"] for r in self.log)
        self.out("")
        self.out(s("── Your results " + "─" * (WIDTH - 16), "dim"))
        self.out(f"  Appropriate reliance          {appropriate}/{n}")
        self.out(f"  Wrong advice followed         {over}/{len(wrong)}   (over-reliance)")
        self.out(f"  Good advice rejected          {under}/{right}   (under-reliance)")
        if self.mode == "linked":
            self.out(f"  Key claims checked            {checked}/{n}")
        self.out("")
        for r in self.log:
            sc = next(x for x in self.scenarios if x["id"] == r["scenario"])
            colour = {"appropriate": "green", "over-reliance": "red", "under-reliance": "yellow"}[r["outcome"]]
            self.out(f"  {sc['title']:<38} AI {'right' if sc['aiCorrect'] else 'wrong':<6} " + s(r["outcome"], colour))
        for r in self.log:
            if not r["aiCorrect"]:
                sc = next(x for x in self.scenarios if x["id"] == r["scenario"])
                self.out(s(wrap(f"{sc['title']}: {sc['errorNote']}", "  "), "dim"))

    def save_log(self):
        if not self.log:
            return None
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"session-{dt.datetime.now():%Y%m%d-%H%M%S}-{self.mode}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            w.writeheader()
            w.writerows(self.log)
        return path

    def run(self):
        try:
            self.intro()
            for i, sc in enumerate(self.scenarios, 1):
                self.run_trial(i, sc)
        except (KeyboardInterrupt, EOFError):
            self.out("\nSession ended early.")
        self.summary()
        path = self.save_log()
        if path:
            self.out(self.s(f"\nInteraction log saved to {path}", "dim"))


def load_scenarios(path=HERE / "scenarios.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    p = argparse.ArgumentParser(description="MoneyCheck: AI money advice you can check (text prototype)")
    p.add_argument("--mode", choices=MODES, default="linked", help="explanation mode (default: linked)")
    p.add_argument("--no-nudge", action="store_true", help="turn off the soft nudge")
    p.add_argument("--answer-key", action="store_true", help="show whether the AI was right after each decision")
    p.add_argument("--no-color", action="store_true", help="plain text output")
    p.add_argument("--fast", action="store_true", help="skip the typing delay")
    a = p.parse_args(argv)
    color = not a.no_color and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    if os.name == "nt":
        os.system("")  # enables ANSI colours in the Windows terminal
    Session(load_scenarios(), mode=a.mode, nudge=not a.no_nudge, answer_key=a.answer_key,
            color=color, delay=0 if a.fast else 1.0).run()


if __name__ == "__main__":
    main()
