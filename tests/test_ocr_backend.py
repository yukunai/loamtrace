from pathlib import Path

from loamtrace.services import ocr_backend


def test_find_tesseract_prefers_bundled_ocr_root(tmp_path, monkeypatch):
    ocr_root = tmp_path / "ocr"
    binary = ocr_root / "bin" / "tesseract"
    tessdata = ocr_root / "share" / "tessdata"
    binary.parent.mkdir(parents=True)
    tessdata.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)

    monkeypatch.setenv("LOAMTRACE_OCR_ROOT", str(ocr_root))
    monkeypatch.setenv("TESSERACT_CMD", "")

    path = ocr_backend.find_tesseract()

    assert path == str(binary)
    assert ocr_backend.tesseract_env(path)["TESSDATA_PREFIX"] == str(tessdata)
