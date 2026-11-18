"""Cross-lesson repetition: how much each course repeats content between its lessons.

For every slide (and quiz question), find the most similar slide (question) in a
*different* lesson of the same course, using the app's BGE-M3 embeddings.
Run inside the api container, which has the embedding model (from the repository root):

    docker compose --env-file .env -f infra/docker-compose.yml cp packages/eval/benchmark api:/tmp/benchmark
    docker compose --env-file .env -f infra/docker-compose.yml exec -T api python /tmp/benchmark/repetition.py \n        /tmp/benchmark/results/qwen-7b/requests.jsonl /tmp/benchmark/results/gemini-flash/requests.jsonl
"""
import json
import sys

import numpy as np

from app.core.llm.embeddings import embed_texts


def load(path):
    slides, questions = [], []
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        ref = r.get("ref") or {}
        if r["task"] == "ragtruth_grounding":
            text = r["fields"]["response"].split("\nSpeaker notes:")[0]  # on-slide text only
            slides.append((ref.get("lesson_id"), text))
        elif r["task"] == "oak_distractors":
            questions.append((ref.get("lesson_id"), r["fields"]["question"]))
    return slides, questions


def cross_lesson(items):
    if len(items) < 2:
        return None
    lessons = [l for l, _ in items]
    v = np.array(embed_texts([t for _, t in items]), dtype=float)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    sim = v @ v.T
    same = np.array([[a == b for b in lessons] for a in lessons])
    sim[same] = -1.0
    best = sim.max(axis=1)
    j = sim.argmax(axis=1)
    pairs = sorted({(min(i, int(j[i])), max(i, int(j[i]))) for i in range(len(items))}, key=lambda p: -sim[p])
    return {
        "n": len(items),
        "lessons": len(set(lessons)),
        "mean_nearest_other_lesson": round(float(best.mean()), 3),
        "share_ge_0.80": round(float((best >= 0.80).mean()), 3),
        "count_ge_0.80": int((best >= 0.80).sum()),
        "count_ge_0.85": int((best >= 0.85).sum()),
        "count_ge_0.90": int((best >= 0.90).sum()),
        "top_pairs": [{"sim": round(float(sim[a, b]), 3), "a": items[a][1][:160], "b": items[b][1][:160]} for a, b in pairs[:5]],
    }


out = {}
for path in sys.argv[1:]:
    slides, questions = load(path)
    out[path] = {"slides": cross_lesson(slides), "quiz_questions": cross_lesson(questions)}
print(json.dumps(out, indent=1, ensure_ascii=False))
