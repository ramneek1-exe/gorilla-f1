"""Terminal menu for picking one of the saved races in data/."""

import sys

try:
    import readline  # noqa: F401  (arrow keys and line editing in input(); not on Windows)
except ImportError:
    pass

from gorilla.dataset import list_datasets



# helper function to describe a dataset.
def describe(meta):
    return f"{meta['year']} {meta['event']} ({meta['session']})"

# helper function to choose a dataset.
def choose_dataset():
    """List the saved races and ask the user to pick one. Returns (path, meta)."""
    datasets = list_datasets()
    if not datasets:
        sys.exit("No races found in data/. Download one first with:\n"
                 "    python -m scripts.export_session 2025 Monza R")

    print("\nSaved races:")
    for i, (_, meta) in enumerate(datasets, start=1):
        print(f"  {i}. {describe(meta)}")

    while True:
        try:
            answer = input(f"\nPick a race (1-{len(datasets)}, or q to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit("\nCancelled.")
        if answer.lower() in ("q", "quit", "exit"):
            sys.exit(0)
        if answer.isdigit() and 1 <= int(answer) <= len(datasets):
            return datasets[int(answer) - 1]
        print(f"Please type a number from 1 to {len(datasets)}.")
