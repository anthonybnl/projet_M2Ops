from la_gazette_des_sorciers.main import main as main_gazette


def test_run():
    print("dummy test")
    main_gazette()
    assert 2 + 3 == 5
