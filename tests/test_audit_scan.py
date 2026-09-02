import json

from audit.scan import find_projects, main, scan_project, to_markdown


def _tree(root):
    (root / "pyproj" / "src").mkdir(parents=True)
    (root / "pyproj" / "pyproject.toml").write_text('[project]\ndependencies = ["numpy>=1", "pandas"]\n')
    (root / "pyproj" / "src" / "a.py").write_text("print('hi')\n")
    (root / "pyproj" / "README.md").write_text("# PyProj\nDoes a thing.\n")
    (root / "g4" ).mkdir()
    (root / "g4" / "CMakeLists.txt").write_text("find_package(Geant4 REQUIRED)\n")
    (root / "g4" / "main.cc").write_text("#include G4RunManager.hh\n// radial energy deposition PSF\n")
    (root / "g4" / "run.mac").write_text("/run/beamOn 1000\n")
    (root / "matlab").mkdir()
    for n in "abc":
        (root / "matlab" / f"{n}.m").write_text("x = 1;\n")
    (root / "work").mkdir()
    (root / "work" / "requirements.txt").write_text("requests\n")
    (root / "work" / "notes.md").write_text("Chamber recipe from Fab2 tool 3\n")
    (root / "node_modules" / "junk").mkdir(parents=True)
    (root / "node_modules" / "junk" / "package.json").write_text("{}")
    (root / "loose.txt").write_text("nothing")


def test_find_and_scan(tmp_path):
    _tree(tmp_path)
    found = {p.name for p in find_projects([tmp_path])}
    assert found == {"pyproj", "g4", "matlab", "work"}
    by = {p.name: scan_project(p) for p in find_projects([tmp_path])}
    assert by["pyproj"]["primary_language"] == "python"
    assert by["pyproj"]["dependencies"]["pyproject.toml"] == ["numpy", "pandas"]
    assert by["pyproj"]["readme"] == "PyProj"
    assert by["g4"]["geant4"] is True and "main.cc" in by["g4"]["psf_hits"]
    assert by["g4"]["dependencies"]["CMakeLists.txt"] == ["Geant4"]
    assert "geant4-macro" in by["g4"]["languages"]
    assert by["matlab"]["primary_language"] == "matlab" and by["matlab"]["n_files"] == 3
    assert by["work"]["flag_hits"] == ["notes.md"]
    assert by["pyproj"]["flag_hits"] == [] and by["pyproj"]["geant4"] is False
    md = to_markdown(list(by.values()))
    assert "EMPLOYER?" in md and "| g4 |" in md


def test_cli_writes_outputs(tmp_path):
    _tree(tmp_path)
    out, md = tmp_path / "o" / "inv.json", tmp_path / "o" / "inv.md"
    assert main([str(tmp_path), "--out", str(out), "--md", str(md)]) == 0
    inv = json.loads(out.read_text())
    assert len(inv) == 4 and md.exists()
