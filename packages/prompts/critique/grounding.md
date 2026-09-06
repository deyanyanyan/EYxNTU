Evaluate GROUNDING: is every factual claim in the content supported by the references?

Audience: {audience}
Learning objectives: {objectives}

=== REFERENCES ===
{rag_context}

=== CONTENT UNDER REVIEW ===
{content}

Instructions:
- List each claim that is NOT supported, contradicted, or over-generalised relative to the references (put them in `issues`, one per line, quoting the offending text).
- Ignore style; only judge factual support.
- Score 5 = fully traceable; 3 = minor unsupported detail; 0 = mostly fabricated.
