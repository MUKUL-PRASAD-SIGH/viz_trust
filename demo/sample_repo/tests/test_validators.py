from app.validators import clean_name, valid_email, valid_password


def test_valid_email():
    assert valid_email("a@b.co")
    assert not valid_email("nope")


def test_valid_password():
    assert valid_password("abcdefg1")
    assert not valid_password("abcdefgh")


def test_clean_name():
    assert clean_name("  grace   hopper ") == "Grace Hopper"
