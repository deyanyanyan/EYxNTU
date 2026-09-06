Generate {count} multiple-choice questions ({difficulty_mix}).

Learning objectives to assess:
{objectives}

Already-existing questions (do not duplicate their concepts):
{existing}

=== REFERENCES ===
{rag_context}

Rules:
1. Each question tests one concept from the references.
2. `correct_answer` and the 3 `distractors` must be the same kind of thing and similar length.
3. `source_span` is copied character-for-character from one reference. Stop at the end of the sentence.
4. `reference` is the number in square brackets the span came from.
5. Do not mention "the document" or "the references" in the stem.
