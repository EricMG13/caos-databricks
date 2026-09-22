---
module: CP-0
blocks: [instruction, gate_instruction, tagged, host_steps, final_check, cp0_final_check]
conditional: []
---

# Prompt for CP-0

The host renders the blocks above from `icm/shared/prompt/` in this order, with the authority, upstream, citation-register, research-brief, source-preparation and evidence sections between them as `caos/methodology/invocation.py` assembles them. A conditional block is rendered only when the pinned route carries CP-CF. The rendered bytes are parity-tested against the legacy host.
