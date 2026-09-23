---
module: CP-3D
blocks: [instruction, tagged, host_steps, final_check]
conditional: [validator_feedback]
---

# Prompt for CP-3D

The host renders the blocks above from `icm/shared/prompt/` in this order, with the authority, upstream, citation-register, research-brief, source-preparation and evidence sections between them as `caos/methodology/invocation.py` assembles them. A conditional block is rendered only under the condition the stage contract's Inputs table names for it. A first attempt's rendered bytes are parity-tested against the legacy host.
