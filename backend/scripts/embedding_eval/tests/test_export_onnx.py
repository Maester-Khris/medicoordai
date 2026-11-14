import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.embedding_eval.export_onnx import QuantConfig, choose_quantization, min_cosine, read_cpu_flags  # noqa: E402


def test_vnni_flags_select_signed_int8():
    for flag in ("avx512_vnni", "avx_vnni"):
        assert choose_quantization({"avx2", flag}) == QuantConfig(weight_type="QInt8", reduce_range=False)


def test_no_vnni_selects_unsigned_with_reduce_range():
    assert choose_quantization({"avx2", "avx512f"}) == QuantConfig(weight_type="QUInt8", reduce_range=True)
    assert choose_quantization(set()) == QuantConfig(weight_type="QUInt8", reduce_range=True)


def test_read_cpu_flags_parses_a_fixture_cpuinfo(tmp_path):
    p = tmp_path / "cpuinfo"
    p.write_text("processor\t: 0\nmodel name\t: X\nflags\t\t: fpu avx2 avx512_vnni sse4_2\n\nprocessor\t: 1\nflags\t\t: fpu avx2\n")
    assert read_cpu_flags(str(p)) == {"fpu", "avx2", "avx512_vnni", "sse4_2"}  # the first flags line is enough: cores share an ISA
    assert read_cpu_flags(str(tmp_path / "missing")) == set()  # no /proc/cpuinfo (not Linux): fall back to the safe unsigned config


def test_min_cosine_over_paired_vectors():
    a = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    b = np.array([[1.0, 0.0], [0.6, 0.8]], dtype=np.float32)
    assert min_cosine(a, b) == pytest.approx(0.8)
    assert min_cosine(a, a) == pytest.approx(1.0)
