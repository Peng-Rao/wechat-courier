from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_reader_has_separate_frozen_entrypoint_and_analysis():
    spec = (ROOT / "build/build.spec").read_text(encoding="utf-8")
    assert '"contact_reader_main.py"' in spec
    assert 'name="wechat-contact-reader"' in spec
    assert "contact_exe," in spec
    assert "sqlcipher3._sqlite3" in spec
    assert (ROOT / "contact_reader_main.py").is_file()


def test_sqlcipher_is_pinned_and_third_party_notices_included():
    assert "sqlcipher3==0.6.3" in (ROOT / "requirements.txt").read_text()
    notices = ROOT / "licenses/wechat-contact-exporter-LICENSE.txt"
    assert notices.is_file()
    assert "MIT License" in notices.read_text()
    assert '"licenses"' in (ROOT / "build/build.spec").read_text(encoding="utf-8")


def test_installer_closes_contact_reader_before_replacing_binaries():
    script = (ROOT / "installer/setup.nsi").read_text(encoding="utf-8-sig")
    startup = script.split("Function .onInit", 1)[1].split("FunctionEnd", 1)[0]
    assert 'taskkill /F /IM "wechat-contact-reader.exe"' in startup
