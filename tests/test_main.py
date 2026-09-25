from intrader.__main__ import main


def test_main_prints_version(capsys) -> None:
    result = main()

    assert result == 0
    assert capsys.readouterr().out.strip() == "Intrader 0.1.0"
