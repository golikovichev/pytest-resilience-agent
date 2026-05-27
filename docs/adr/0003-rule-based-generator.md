# ADR 0003: Rule-based scenario picker, not LLM, for v0.1 generator

## Status

Accepted for v0.1; revisit for v0.2.

## Context

The generator turns a Lark-reported failure (free-text last_failure
string + test name) into a resilience pytest file with the right chaos
scenarios applied. Two implementations were on the table:

1. Rule-based regex mapping: pattern → scenario list.
2. LLM-driven classifier: send the failure text to a Gemini agent and
   ask it which scenarios apply.

## Decision

Ship the rule-based mapping in v0.1. The rules live in `generator.py`,
are ordered (first match wins), and are easy to read in one glance.

## Consequences

- Generation is deterministic. The same failure produces the same test
  file every run; engineers can trust the diff.
- Adding a new scenario means adding a regex rule. No prompt
  engineering, no LLM API key, no cost per generation.
- The hackathon judges can audit the mapping in 30 seconds.

## Why not the LLM-driven path

The LLM-driven classifier would be a more interesting demo, but it adds
real cost (each generation hits a model), introduces a flake source
(model variability), and requires API credentials to run the test
suite. For a hackathon submission whose contract is «judges clone and
run», the rule-based path is the right v0.1 trade-off.

## When to revisit

v0.2 should add an optional LLM classifier behind the same
`pick_scenarios` interface so users can opt in. The interface stays
stable.
