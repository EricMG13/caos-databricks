---
module: CP-2G
blocks: [instruction, tagged, host_steps, final_check]
conditional: [forecast_extension]
---

# Prompt for CP-2G

The host renders the blocks above from `icm/shared/prompt/` in this order, with the authority, upstream, citation-register, research-brief, source-preparation and evidence sections between them as `caos/methodology/invocation.py` assembles them. A conditional block is rendered only when the pinned route carries CP-CF. The rendered bytes are parity-tested against the legacy host.
