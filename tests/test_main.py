from intrader import __version__
from intrader.__main__ import main


def test_main_prints_version(capsys) -> None:
    result = main()

    assert result == 0
    assert capsys.readouterr().out.strip() == f"Intrader {__version__}"
