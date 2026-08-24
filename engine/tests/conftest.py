from __future__ import annotations

import pytest

from helpers import make_zone


@pytest.fixture
def zone():
    return make_zone()
