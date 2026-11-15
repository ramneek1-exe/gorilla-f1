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

## Race data

Telemetry is downloaded once with FastF1 and saved to `data/` as one file per
session. Every other script reads those files, so the project runs offline and
needs no F1 account.

The saved races are already in `data/`. To add another (this needs an F1 TV
account; FastF1 asks for the email and password):

```
python -m scripts.export_session 2025 Monaco R
```

The arguments are the season, the event name and the session (`R` race,
`Q` qualifying). FastF1's download cache goes in `cache/`, which is not part of
the repository and can be deleted after exporting.

## Inspect a race

Compress every lap of a saved race, check that it decodes back exactly, and
print sizes and statistics. Pick the race from the menu:

```
python -m scripts.inspect_session
```

## Query a race

Pick a race, then look up any driver, lap and one or more channels (for example
`Speed RPM Throttle`, or `all`). Each answer is decoded from the compressed
store, checked against an uncompressed copy, and timed.
The stores are built the first time a race is opened and saved in `results/`.

```
python -m scripts.query
```

## Layout

```
gorilla/bitio.py        bit-level writer and reader
gorilla/timestamps.py   delta-of-delta timestamp encoder and decoder
gorilla/values.py       XOR value encoder and decoder
gorilla/block.py        block format: one driver's lap, all channels
gorilla/ingest.py       loads FastF1 car data and splits it into laps
gorilla/dataset.py      saves and loads race data files in data/
gorilla/store.py        indexed store of a whole race, with queries
data/                   saved race data
scripts/                command-line tools
tests/                  unit tests
```

## Run the experiments

Run every experiment on every saved race. Tables (CSV), charts (PNG) and a
summary go to `results/experiments/`. This takes several minutes.

```
python -m scripts.experiments
```
