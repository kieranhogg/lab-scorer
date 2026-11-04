from labtools import helpme
from labtools.state import read_help, set_help


def test_help_raises_the_flag(capsys):
    helpme.main()
    assert read_help()
    assert "flagged" in capsys.readouterr().out


def test_asking_twice_keeps_one_flag(capsys):
    helpme.main()
    capsys.readouterr()
    helpme.main()
    assert "already" in capsys.readouterr().out
    assert read_help()


def test_flag_can_be_cleared():
    set_help(True)
    set_help(False)
    assert not read_help()
