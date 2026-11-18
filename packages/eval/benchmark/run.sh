#!/bin/sh
# Grade the reviewer demo course and the two writer courses with a hosted judge, using the
# trained reviewer's prompts, then summarise. Run from the repository root:
#
#   sh packages/eval/benchmark/run.sh [model] [base-url] [key-variable]
#
# Defaults: gpt-5.5 on the OpenAI API with OPENAI_API_KEY. For Gemini:
#   sh packages/eval/benchmark/run.sh gemini-pro-latest https://generativelanguage.googleapis.com/v1beta/openai GEMINI_API_KEY
#
# Needs a Python with numpy, scipy and pyyaml, plus `pip install -e packages/eval/training --no-deps`
# (set PY to that interpreter). The key is read from the environment or from .env.
set -e
MODEL=${1:-gpt-5.5}
BASE_URL=${2:-https://api.openai.com/v1}
KEY_ENV=${3:-OPENAI_API_KEY}
PY=${PY:-python}
B=packages/eval/benchmark
R=$B/results
DEMO=packages/eval/training/results/review-demo     # requests and the trained 27B's results

run() { $PY $B/review_openai.py --base-url "$BASE_URL" --model "$MODEL" --key-env "$KEY_ENV" $EXTRA --requests "$1" --out "$2"; }
mkdir -p $R/review-demo
run $DEMO/requests.jsonl            $R/review-demo/results-$MODEL.jsonl
run $R/qwen-7b/requests.jsonl       $R/qwen-7b/results-$MODEL.jsonl
run $R/gemini-flash/requests.jsonl  $R/gemini-flash/results-$MODEL.jsonl
rm -f $R/*/results-$MODEL.predictions.jsonl     # raw generations; the results files carry the same rows

$PY $B/summarize.py agree 27B=$DEMO/results.jsonl "$MODEL"=$R/review-demo/results-$MODEL.jsonl > $R/agreement-$MODEL.json
$PY $B/summarize.py course qwen=$R/qwen-7b/results-$MODEL.jsonl gemini=$R/gemini-flash/results-$MODEL.jsonl > $R/courses-$MODEL.json
echo "done: $R/agreement-$MODEL.json $R/courses-$MODEL.json"
