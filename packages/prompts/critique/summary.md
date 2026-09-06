Combine the three reviews into a decision.

Grounding review: {grounding}
Coherence review: {coherence}
Pedagogy review: {pedagogy}

=== REFERENCES ===
{rag_context}

=== CONTENT ===
{content}

Instructions:
- `overall_score`: weighted mean with grounding counting double.
- `revise`: true if overall_score < 4 or any unsupported claim exists.
- `revision_instructions`: numbered, concrete edits (what to change, where, and which reference to use).
- `unsupported_claims`: verbatim claims that must be removed or re-sourced.
