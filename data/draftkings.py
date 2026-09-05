"""
data/draftkings.py
------------------
DraftKings player pool CSV ingestion.
Re-exports from ingestion/csv_loader.py so both import paths work
while the project transitions to the data/ layout.
"""

from ingestion.csv_loader import (
    load_from_dataframe,
    load_from_file,
    load_from_upload,
    load_from_url,
)

__all__ = [
    "load_from_dataframe",
    "load_from_file",
    "load_from_upload",
    "load_from_url",
]
