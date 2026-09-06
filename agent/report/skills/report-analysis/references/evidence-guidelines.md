# Evidence and Claim Guidelines

## Evidence states

- `supported`: the deterministic result supports the tested Predicate.
- `not_supported`: the calculation was conclusive and did not support it.
- `inconclusive`: sample, quality, or method conditions prevent a conclusion.
- `tool_failed`: no valid Evidence was produced; apply the system recovery policy.

Do not convert `inconclusive` or `tool_failed` into `not_supported`.

## Claim binding

- Bind a derived Claim to the exact `predicate_evidence_id` with `supported=true` and
  parent `analysis_status=conclusive`.
- Bind every displayed number to an authoritative Fact or Evidence numeric value.
- Use at least two distinct Evidence items for a synthesis Claim.
- Preserve limitations and quality references that constrain the Evidence.
- Omit a Claim when an exact binding cannot be formed.

Data Evidence supports what occurred in this session. Future LiteratureEvidence may
support definitions, background, interpretation boundaries, or limitations, but it
must not replace session Evidence or turn association into causation.

