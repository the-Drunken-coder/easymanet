import pytest

from easymanet.format import human_size


def test_human_size_rejects_negative_values():
    with pytest.raises(ValueError, match="non-negative"):
        human_size(-1)


def test_human_size_formats_positive_values():
    assert human_size(0) == "0 B"
    assert human_size(1536) == "1.5 KB"
