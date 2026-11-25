# MoneyCheck: AI money advice you can check (text-based prototype)

**README prose word count:** about 1260 (code blocks and commands excluded)

IIS Assignment 2 prototype. A text-based, interactive system that tests whether AI explanations linking each claim to its source help people tell good advice from bad, without the extra effort of cognitive forcing. It builds on my A1 literature review, *Explaining Is Not Calibrating*.

-- **Submitted commit/release:** [v1.0-submission](https://github.com/stephaniedikeanyakorah/moneycheck/releases/tag/v1.0-submission)

## Project status

| Part | Status |
|---|---|
| Three explanation modes: A none / B standard paragraph / C source-linked | Implemented |
| Type a claim number to see its quoted source beside what the AI said | Implemented |
| Reliability labels (✓ Official / Company guide / ! Unverified forum post) and "last checked" dates | Implemented |
| "Advice depends on this" marker on the key claim | Implemented |
| Soft nudge before following advice whose key claim is unchecked | Implemented |
| `report N` to flag a source that looks wrong | Implemented (human review of reports is simulated) |
| AI declines when no source covers the question | Implemented (scripted case) |
| Repair messages for unrecognised input, `help` command | Implemented |
| Interaction log (CSV) and results summary | Implemented |
| Automated tests | Implemented |
| AI advisor: 9 scenarios, 3 deliberately wrong, 1 where it declines | **Simulated**: scripted answers in `scenarios.json` |
| Live LLM with retrieval generating the claims and citations | Planned |
| Automatic claim–source checking in code | Planned |
| Multi-session use and feedback over time | Planned |

No user testing has been run yet. The tests show the system behaves as designed, not that it improves reliance.

## Technology stack

- **Python 3.8+, standard library only.** No packages, no API key, runs in any terminal, including VS Code's.
- **No AI model is called.** Answers are scripted so I control exactly when the AI is wrong, which is what makes appropriate reliance measurable.
- **Tests:** Python `unittest`.
- **Undecided for the planned version:** which LLM, which retrieval setup, how to store the source corpus.

## Running it (VS Code or any terminal)

1. Open this folder in VS Code (File → Open Folder).
2. Open a terminal (Terminal → New Terminal) and run:

```
python moneycheck.py                    # mode C: source-linked (default)
python moneycheck.py --mode standard    # mode B: standard LLM-style paragraph
python moneycheck.py --mode none        # mode A: recommendation only
```

Use `python3` on a Mac if `python` isn't found.

**Researcher options:** `--no-nudge` turns the nudge off; `--answer-key` shows whether the AI was right after each decision (for demos only); `--fast` skips the typing delay; `--no-color` prints plain text.

**Commands while answering:** a claim number (e.g. `3`) checks that claim; `s` lists sources; `report 3` flags a source; `f` follows the advice; `r` doesn't follow it; `h` shows help; `q` quits. Each session's log is saved to `logs/`.

## Architecture

| File | Role |
|---|---|
| `moneycheck.py` | The whole app: rendering, input loop, nudge rule, scoring, logging |
| `scenarios.json` | The simulated AI: questions, answers, claims and sources. The contract a real LLM would have to fill |
| `test_moneycheck.py` | Automated tests |
| `latest-results.txt` | Output of the latest test run |
| `logs/` | CSV logs, one per session (created on first run; don't commit it) |

**Data model.** Each scenario has `parts` (the answer text, with `{"c": n}` references to claims), `claims` (`text`, `source`, `key`, `matches`), `sources` (`name`, `excerpt` with `<mark>` highlights, `reliability`, `checked`, `url`) and `aiCorrect` / `declined` flags.

**One answer, three modes.** All three modes are built from the same `parts`: A prints only the recommendation; B joins the claims into a paragraph; C adds `[n]` tags, the source list and the commands to check claims. The modes differ in presentation, never in content, so comparing them is fair.

**Per-question state.** A `Trial` object records which claims were opened and reported, whether the nudge was shown and how it was answered, how many inputs weren't understood, and a start time taken once the answer is on screen.

**Nudge rule.** On `f`, the nudge appears only if all of these are true: the mode is C, the nudge is on, the key claim hasn't been opened, and the nudge hasn't already shown for this question. `c` opens the key claim; `f` follows anyway.

**Logging.** Each decision is logged with `scenario, mode, aiCorrect, decision, appropriate, outcome, sourcesOpened, keyChecked, reported, declined, nudgeShown, nudgeResponse, invalidInputs, seconds`. `outcome` is *appropriate* (following right advice or rejecting wrong advice), *over-reliance* (following wrong advice) or *under-reliance* (rejecting right advice).

## How the design uses the module

| Feature | Concept |
|---|---|
| Source shown beside the claim on request | Shown, not just cited; recognition over recall (Norman, 2013); grounding by display (Clark and Brennan, 1991) |
| No reasoning paragraph or warning label in mode C | Printed reasoning persuades whether or not it is correct; fluency is not evidence; ELIZA effect |
| `[n]` tags, the command hint line, "advice depends on this" | Signifiers (Norman, 2013); bounded rationality (Simon, 1955); working memory limits (Cowan, 2001) |
| Reliability labels, dates, `report N` | Grounding doesn't guarantee truth or currency; a citation should be dated and challengeable |
| Declining when no source covers the question | Grice's (1975) maxim of quality |
| Soft nudge | Mixed initiative, act/ask/wait (Horvitz, 1999); a lighter alternative to cognitive forcing |
| Repair messages for unrecognised input | Repair turns in conversational interfaces |
| Typing indicator | Feedback timing (Miller, 1968; Nielsen, 1993) |
| The person always decides | High automation with high human control (Shneiderman, 2022); sense of agency (Haggard, 2017) |
| Over- and under-reliance in the log | Misuse and disuse of automation (Parasuraman and Riley, 1997) |

## Testing

```
python -m unittest test_moneycheck -v
```

The 20 tests (with sub-tests over all 9 scenarios and all 3 modes) drive real sessions with scripted keyboard input and check:

- **Data:** every claim appears once and points to a real, labelled, dated source; each scenario has one key claim; every wrong answer can be caught from what is shown (the key claim contradicts its source, or rests on a forum post).
- **Modes:** tags and sources appear only in mode C, the answer text only in B and C, and each mode is logged.
- **Source linking:** checking LISA claim 3 shows the AI's "10%" beside the source's "25%", plus the date; the forum label, the decline case and `report` work.
- **Nudge:** it appears for an unchecked key claim, not once the claim was checked, not in other modes, and not when switched off. Skipping it is logged.
- **Conversation:** repair messages for unrecognised input and invalid claim numbers; help; the typing indicator appears before the answer; quitting early keeps the answers so far.
- **Scoring:** a scripted full run produces 6/9 appropriate, 2/3 over-reliance, 1/6 under-reliance, and a matching CSV.

**Do the tests catch bugs?** I deliberately broke the nudge rule, then separately scored over-reliance as "appropriate". The tests failed each time, then passed again once the code was restored.

**Latest run:** 20/20 passed (`latest-results.txt`).

## Development record

All files were uploaded in one commit: [d74fdf2](https://github.com/stephaniedikeanyakorah/moneycheck/commit/d74fdf2e04c7f121c7bf8896aba7061736183c37).

- **Stage 1: web prototype.** First built as a web page: three modes, claim-to-source panel, key-claim marker, nudge, logging, then reliability labels, dates, reporting and a decline case. *Checked:* browser tests.
- **Stage 2: moved to a text-based version.** I rebuilt it as a terminal app so the interaction, not the visuals, carries the design. In a text interface every cue has to be in the words (command hints, labels, repair messages), which matches the module's focus on conversational interfaces. Same scenarios and logic, reused from the web version.
- **Stage 3: automated tests.** 20 tests with scripted input; confirmed they catch two deliberately introduced bugs.

## AI assistance

- **Tool:** Claude.
- **What I asked for:** A working prototype, first as a web page and then as a text-based version; writing the tests.
- **What I changed:** I chose the topic, scenarios and design direction from my A1 and the lectures. I had the first web version restyled, then replaced it with a text-based version because the web one felt unrealistic. When reviewing the report, I pushed back on claims that overgeneralised the research and asked for more technical detail and evidence that the system works.
- **How I checked:** ran the tests; played through every scenario in every mode; checked each source figure against the live GOV.UK, FCA, MoneyHelper and Experian pages; read the code for the nudge rule and scoring.

## Additional files

None. Everything is in this repository.
