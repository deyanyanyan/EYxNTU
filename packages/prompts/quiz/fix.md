This question failed validation. Repair it while keeping the same concept.

Issues:
{issues}

Question:
{question}

=== REFERENCES ===
{rag_context}

Return the corrected question in the `question` field. If the issue is `span_not_found`, choose a sentence that actually appears verbatim in the references. If `answer_leak`, rewrite the stem so it does not contain the answer.
