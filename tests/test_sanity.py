"""Test sanité : l'environnement est correctement installé."""

import sys


def test_python_version():
    assert sys.version_info[:2] == (3, 11)


def test_dotenv_importable():
    import dotenv  # noqa: F401
