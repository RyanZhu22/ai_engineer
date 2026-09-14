"""检索基准命令行参数测试。"""
import argparse

import pytest

from evals.bench_retrieval import embedding_batch_size


def test_embedding_batch_size_bounds():
    assert embedding_batch_size("32") == 32
    assert embedding_batch_size("256") == 256
    for value in ("0", "257", "invalid"):
        with pytest.raises(argparse.ArgumentTypeError):
            embedding_batch_size(value)
