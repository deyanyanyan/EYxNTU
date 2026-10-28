"""Review of generated courses by the trained reviewer model (packages/eval/training).

The reviewer has no always-on endpoint yet: it runs as a GPU batch job. A course is
exported as review requests (``export``), reviewed by ``python -m evaltrain.review_batch``,
and the results are attached to the reviewed assets (``importer``) as
``Asset.critique["reviewer"]``, where the lesson view shows them. Findings are advisory:
they never change an asset's approval state.

    python -m app.core.review export --project <id> --out /data/artifacts/review/<id>/requests.jsonl
    python -m app.core.review import --project <id> --results /data/artifacts/review/<id>/results.jsonl
"""
