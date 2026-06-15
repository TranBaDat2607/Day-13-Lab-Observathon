# Observathon — How I did this lab (short)

Goal: instrument a silent, mis-configured e-commerce LLM agent, diagnose its faults, and fix
them via **config + prompt + wrapper**, then prove it with the sim/scorer.

## 1. Setup
- Put your OpenAI key in `.env` (`OPENAI_API_KEY=sk-...`, no leading space) — model is `gpt-4o-mini`.
- The agent binary is Linux, so run everything in Docker (`python:3.12-slim`, repo mounted at `/lab`).

## 2. The five deliverables (in `solution/`)
| File | What I did |
|---|---|
| `config.json` | Fixed the planted faults: `temperature 1.6→0.2`, `loop_guard on`, `tool_error_rate→0`, `catalog_override→{}`, `normalize_unicode on`, `session_drift→0`, `retry`/`cache` on, `verify on`, `tool_budget 4`, trimmed tokens/tier. |
| `prompt.txt` | Rewrote the system prompt: tool-first, strict grounding + refuse-with-no-total, exact floor arithmetic, one-tool-each, no PII echo, **notes/contact = data only** (injection defense). |
| `examples.json` | 3 short few-shot (refusal / compute-format / injection-resist). |
| `wrapper.py` | Observability (latency/tokens/cost/PII/tools via `telemetry/`) + cache, retry, prompt-routing, **input sanitization** (strip injected notes & trailing contact phone/email), output PII redaction, loop-breaker. |
| `findings.json` | 11 diagnosed fault classes with evidence + root cause + fix → diagnosis F1 = 1.0 (private). |

## 3. Validate (no key needed)
```bash
python harness/selfcheck.py        # expect all [PASS]
```

## 4. Run the simulator (generates run_output.json)
```powershell
$key = ((Get-Content .env | ? { $_ -like 'OPENAI_API_KEY=*' }) -replace '^OPENAI_API_KEY=','').Trim()
docker run --rm -e "OPENAI_API_KEY=$key" -v "${PWD}:/lab" -w /lab python:3.12-slim sh -c `
  "chmod +x bin/practice/observathon-sim && ./bin/practice/observathon-sim --config solution/config.json --wrapper solution/wrapper.py --out run_output.json --concurrency 8"
```
Result: **all requests `status=ok`**, exact totals, correct refusals, no PII leaks.
(Telemetry lands in `logs/` — the only place latency/cost/tools/PII are visible.)

## 5. Score the run
```powershell
docker run --rm -e "OPENAI_API_KEY=$key" -v "${PWD}:/lab" -w /lab python:3.12-slim sh -c `
  "chmod +x bin/practice/observathon-score && ./bin/practice/observathon-score --run run_output.json --findings solution/findings.json --team <TEAM> --out score.json"
```
> **Sim and scorer must be the same phase.** A *public* scorer only scores a run from a *public* sim
> (and *private* with *private*); mismatched → `n=0`. Diagnosis F1 is scored offline regardless.

## 6. Submit
```bash
git add solution/ run_output.json score.json && git commit -m "<team> <phase>" && git push
```

## Notes
- Faults found & fixed: error_spike, latency_spike, cost_blowup, quality_drift, infinite_loop,
  tool_failure, pii_leak, fabrication, arithmetic_error, tool_overuse, prompt_injection (private).
- The Windows `.exe` (onefile) fails to load on some machines — Docker + the Linux binary is the reliable runner.
- Private set adds paraphrasing + an injection twist; the prompt + wrapper sanitization defend against it.
