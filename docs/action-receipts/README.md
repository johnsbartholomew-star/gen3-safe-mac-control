# Action Receipts (experimental, not yet run on a Mac)

**Status:** an experimental first version is in `safe_mac_control/receipts.py`, with 19 offline tests in
`tests/test_receipts.py`. It has **not** been run against a real Mac app: the Accessibility readings are
tested only with a stand-in. Not released or supported, and not part of the `0.1.0-alpha.1` release or its `MANIFEST.json`.
The planted-failure evaluation below has not been run.

```sh
python3 -m safe_mac_control.receipts begin --step S-001 --expect expect.json --receipts ./receipts
#   ... the agent performs its action ...
python3 -m safe_mac_control.receipts end   --step S-001 --receipts ./receipts
```

See `SPEC.md` for the expectation format and exact rules.

## The problem

An AI agent can read every pixel on a screen correctly and still not know what happened:
whether the save finished, which document received it, or whether a click went through twice.
Most computer-use tools check *that an action was accepted*, not *what actually changed*.

## The idea

A small, local, open-source observer that sits **under any computer-use agent** (Claude, OpenAI,
Microsoft UFO², or this repo's own controls) and writes an **action receipt** for each step:

1. **Before** the action: record the state from the most reliable source that is openly available.
2. **After** the action: record it again, from **two independent sources** where possible.
3. **Compare** and return one plain verdict, with the evidence and where each reading came from.

It **only watches and reports**. It never clicks, types, retries or changes anything.

## Verdicts

These follow this repo's existing vocabulary (`VERIFIED`, `UNKNOWN_EFFECT`).

| Verdict | Meaning |
|---|---|
| `VERIFIED` | The expected change was seen, by two agreeing sources. |
| `NO_CHANGE` | Nothing relevant changed. The action did not take effect. |
| `REPEATED` | The change happened more than once (for example, a double submit). |
| `WRONG_TARGET` | Something changed, but not the expected document, window or field. |
| `UNKNOWN_EFFECT` | Sources disagree or a reading is missing. Never guessed; never retried. |

## Where readings come from (highest first)

The observer always uses the highest level it is **openly allowed** to read, and records which one it used.

1. **Generated-interface descriptions** an agent publishes, such as [A2UI](https://github.com/google/A2UI) JSON or MCP Apps.
2. **The app's own data**: a file's size, modified time and content hash; an app API or document state.
3. **The interface layer**: macOS Accessibility (window, focused element, values); page structure (DOM) in a browser the user controls.
4. **Pixels**: screenshots and text recognition. Last resort, lowest confidence.

## Ground rules

- **Read only what is openly offered.** No code injection into other apps, no disabling macOS security, no private APIs.
- **Private by default.** Receipts store hashes, not document text, unless the user opts in. Receipts stay on the user's machine.
- **Never decide on one source when two disagree.** The answer is `UNKNOWN_EFFECT`.
- **No network, no paid API, no account.** Standard library plus the existing Swift helper.

## How it relates to what's already here

This repo's controls already check one postcondition for their own `press` action and keep per-request receipts.
Action Receipts would generalise that idea: the same kind of receipt for **any** agent's action, using several
observation sources instead of one.

## First proof before building

A 20-task failure test on a Mac (see `SPEC.md`, "Evaluation"). If a two-source receipt does not catch clearly more
planted failures than a screenshot-only check, the tool is not worth building.

See `SPEC.md` for the receipt format and the evaluation.
