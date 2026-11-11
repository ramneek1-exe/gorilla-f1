# Gorilla compression on F1 telemetry

CPSC 4660 (Fall 2026) course project. A from-scratch Python implementation of the
time-series compression scheme from Pelkonen et al., "Gorilla: A Fast, Scalable,
In-Memory Time Series Database" (VLDB 2015, Section 4.1), applied to Formula 1
car telemetry from FastF1.

## Setup

    python -m venv .venv
    source .venv/bin/activate        # Windows: .venv\Scripts\activate
    pip install -r requirements.txt

## Run the tests

    pytest

## Layout

    gorilla/bitio.py      bit-level writer and reader
    tests/                unit tests
