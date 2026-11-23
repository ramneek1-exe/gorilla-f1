"""Command-line tools for the project. Run them with python -m scripts.<name>."""

import sys

# Some Windows terminals (and output redirected to a file) use an encoding that
# cannot show every character. Print a placeholder instead of crashing.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")
