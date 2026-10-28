Rewrite one multiple-choice question.

Learning objectives it assesses:
{objectives}

The question now (JSON):
{question}

What to change:
{instructions}

=== REFERENCES ===
{rag_context}

Rules:
1. Test the same concept unless the instructions say otherwise.
2. `correct_answer` and the 3 `distractors` must be the same kind of thing and similar length. Each distractor must be wrong according to the references.
3. `source_span` is copied character-for-character from one reference. Stop at the end of the sentence.
4. `reference` is the number in square brackets the span came from.
5. Do not mention "the document" or "the references" in the stem.
