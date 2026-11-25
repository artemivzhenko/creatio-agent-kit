import gate


def test_the_repo_names_are_mapped_to_the_sites_prefix():
    assert gate.mapped("open UsrOrderForm for UsrVisibleRecord", "Abc") == "open AbcOrderForm for AbcVisibleRecord"
    assert gate.mapped("usr-form-visible.act", "Abc") == "abc-form-visible.act"
    assert gate.mapped("Usrx USR_ order", "Abc") == "Usrx USR_ order", "only Usr+Capital and usr- are names"


def test_the_bed_line_is_read_from_the_leading_comments_only():
    assert gate.bed_of("# writes\n# bed bench\nuse Supervisor\n") == "bench"
    assert gate.bed_of("# writes\nuse Supervisor\n") == "test-package"
    assert gate.bed_of("use Supervisor\n# bed bench\n") == "test-package", "after the first command it is not a header"


def test_a_bench_case_is_copied_as_it_is_and_the_others_are_renamed():
    import tempfile
    from pathlib import Path
    keep = {"bench-001-ac03-insert-label", "usr-form-visible"}
    skip = {p.stem for f in ("Cases", "ProcessCases") for p in (gate.HERE / f).glob("*.act")} - keep
    with tempfile.TemporaryDirectory() as d:
        beds: dict[str, str] = {}
        gate.copy_cases(Path(d), "Abc", skip, beds)
        assert "UsrOrder" in (Path(d) / "Cases" / "bench-001-ac03-insert-label.act").read_text(encoding="utf-8")
        assert "UsrOrder" not in (Path(d) / "Cases" / "abc-form-visible.act").read_text(encoding="utf-8")
        assert beds == {"bench-001-ac03-insert-label": "bench", "abc-form-visible": "test-package"}


def test_the_counts_are_per_bed():
    beds = {"bench-a": "bench", "abc-b": "test-package"}
    report = "PASS  bench-a   (1s)\nFAIL  abc-b   (1s)\nPASS  abc-c   (1s)\n"
    assert gate.bed_counts(report, beds) == "test-package: 1 passed, bench: 1 passed"


def test_the_page_files_are_copied_and_a_page_a_bench_case_names_stays():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        gate.copy_cases(Path(d), "Abc", set())
        pages = Path(d) / "Configuration" / "pages"
        assert (pages / "UsrOrderBenchForm.json").exists(), "named by a bench case: as it is"
        assert not (pages / "AbcOrderBenchForm.json").exists()
        assert (pages / "AbcOrderForm.json").exists() and not (pages / "UsrOrderForm.json").exists()
