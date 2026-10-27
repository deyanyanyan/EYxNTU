"""``evaltrain <command> [args]``: dispatcher over the module command lines."""
from __future__ import annotations

import importlib
import sys

COMMANDS = {
    "acquire": ("evaltrain.acquire", "download pinned public datasets and write the source manifest"),
    "prepare": ("evaltrain.prepare", "convert raw datasets into split review examples with leakage audits"),
    "lengths": ("evaltrain.lengths", "profile token lengths under the chat template; list over-length examples"),
    "train": ("evaltrain.train", "build the mixture and run (or resume) LoRA training within a walltime budget"),
    "infer": ("evaltrain.infer", "batch inference over prepared examples"),
    "evaluate": ("evaltrain.evaluate", "score predictions per task with grouped confidence intervals"),
    "run-eval": ("evaltrain.run_eval", "inference plus scoring for an experiment arm (base or adapter)"),
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("usage: evaltrain <command> [args]\n")
        for name, (_, help_text) in COMMANDS.items():
            print(f"  {name:<10} {help_text}")
        raise SystemExit(2)
    module = importlib.import_module(COMMANDS[sys.argv[1]][0])
    module.main(sys.argv[2:])


if __name__ == "__main__":
    main()
