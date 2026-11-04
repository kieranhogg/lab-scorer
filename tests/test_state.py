from labtools.state import read_step, write_step


def test_missing_file_is_step_zero():
    assert read_step() == 0


def test_invalid_content_is_step_zero(step_file):
    step_file.write_text("not a number")
    assert read_step() == 0


def test_round_trip():
    write_step(3)
    assert read_step() == 3


def test_student_details_round_trip():
    from labtools.state import read_student, set_student

    assert read_student() == {}
    set_student("Kim", "vscode")
    assert read_student() == {"name": "Kim", "editor": "vscode"}
