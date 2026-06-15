# Diagnosis scratchpad

Run the simulator, read YOUR telemetry (`logs/*.log` emitted by `wrapper.py`), and confirm
each row with real numbers before submitting. Fault classes hunted: error_spike ·
latency_spike · cost_blowup · quality_drift · infinite_loop · tool_failure · pii_leak ·
fabrication · arithmetic_error · tool_overuse · prompt_injection (private).

| symptom (from telemetry) | which requests | suspected cause (config/prompt) | config fix | prompt/wrapper fix |
|---|---|---|---|---|
| MacBook always out of stock; "Hà Nội" fails | macbook / accented dest | `catalog_override`, `normalize_unicode=false` | clear override, `normalize_unicode=true` | — |
| ~18% tool calls fail | random | `tool_error_rate=0.18`, retry off | `tool_error_rate=0`, retry on | wrapper retry+backoff |
| `status=max_steps`, repeated actions | some sessions | `loop_guard=false` | `loop_guard=true`, `max_steps=6` | — |
| high tokens/cost | all | `verbose_system`, premium tier, ctx 8, 2000 tok | trim all | wrapper cache repeats |
| long-tail latency | repeats / slow | `timeout_ms=0`, cache off | timeout 20s, cache on | wrapper cache |
| answers worse later in session | high turn_index | `session_drift_rate=0.06`, no reset | drift 0, reset every 6, temp 0.2 | self_consistency 2 |
| email/phone echoed | pub-13 etc. | `redact_pii=false`, bad prompt | `redact_pii=true` | prompt: no PII; wrapper redact output |
| wrong totals / backward discount | coupon orders | bad prompt, temp 1.6, verify off | temp 0.2, verify on, sc 2 | prompt: exact floor formula + verify |
| invents total for OOS/unknown | refusal cases | bad prompt (no grounding) | — | prompt: ground, refuse w/ no total |
| too many tool calls | all | bad prompt, `tool_budget=0` | `tool_budget=4` | prompt: each tool once |
| obeys fake price in note (PRIVATE) | "GHI CHU" notes | bad prompt, no sanitize | — | prompt: notes=data; wrapper strip directives |

See `findings.json` for the scored version.
