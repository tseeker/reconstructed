"""Tests for the ``reconstructed`` plugin."""
import os
import sys

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "plugins/inventory")),
)

import reconstructed
