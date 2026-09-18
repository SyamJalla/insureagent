"""Package init — runs before every app import.

Cap BLAS thread pools BEFORE numpy/onnxruntime/spaCy load (chromadb and the
guardrail checks pull them in): OpenBLAS otherwise allocates per-core thread
buffers at import and fails outright under memory pressure ("Memory
allocation still failed"). Same cap CI uses for the eval job. setdefault, so
an explicit env override still wins.
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
# Presidio otherwise probes for CUDA by importing torch (if a stale install
# is present, that import can crash outright). We are CPU-only by design.
os.environ.setdefault("PRESIDIO_DEVICE", "cpu")
