# Taken from the pytest documentaion site:
# https://docs.pytest.org/en/latest/example/

import pytest

def pytest_addoption(parser):
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption(
        "--runprop", action="store_true", default=False, help="run very slow property-based tests"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: mark test as slow to run")
    config.addinivalue_line("markers", "proptest: mark test as a very slow property test")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--runslow"):
        # --runslow given in cli: do not skip slow tests
        skip_slow = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
    if not config.getoption("--runprop"):
        skip_prop = pytest.mark.skip(reason="need --runprop option to run")
        for item in items:
            if "proptest" in item.keywords:
                item.add_marker(skip_prop)