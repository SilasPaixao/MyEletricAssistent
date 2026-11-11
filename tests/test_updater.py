from app.updater import parse_version, check_latest, is_configured
import pytest

def test_version_order():
    assert parse_version('v1.2.10') > parse_version('1.2.9')

def test_invalid_version():
    with pytest.raises(ValueError):
        parse_version('1.2')

def test_repo_missing():
    with pytest.raises(ValueError):
        check_latest(repository='invalid')
