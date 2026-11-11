# Gorilla compression on F1 telemetry

CPSC 4660 (Fall 2026) course project. A from-scratch Python implementation of the
time-series compression scheme from Pelkonen et al., "Gorilla: A Fast, Scalable,
In-Memory Time Series Database" (VLDB 2015, Section 4.1), applied to Formula 1
car telemetry from FastF1.

Paper: https://www.vldb.org/pvldb/vol8/p1816-teller.pdf

## Requirements

Python 3.10 or newer.

## Setup

### macOS / Linux

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows (PowerShell)

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks the activate script, run this once and try again:

```
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Windows (Command Prompt)

```
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

Activate the environment again each time you open a new terminal. Your prompt
starts with `(.venv)` when it is active.

## Run the tests

```
pytest
```

## Layout

```
gorilla/bitio.py        bit-level writer and reader
gorilla/timestamps.py   delta-of-delta timestamp encoder and decoder
tests/                  unit tests
```