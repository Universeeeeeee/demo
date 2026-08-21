# Frozen RAG release artifacts

This directory contains reviewed, canonical JSON artifacts promoted from
`data/knowledge/groundedness_review.json`. Production release gates must only
reference files in this tracked directory. Generated or pending local reviews
must never be used directly by the release gate.

Promotion requires every case from the frozen live benchmark exactly once and
binds the review to canonical catalog, manifest, recommendation prompt, and
benchmark-case content digests. Any content drift requires a new benchmark run
and human review before promotion.
