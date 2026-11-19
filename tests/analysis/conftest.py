import warnings

import pytest


@pytest.fixture(autouse=True)
def _quiet_pyfixest():
    # pyfixest warns about singleton fixed effects in small simulated panels; not relevant here.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield
