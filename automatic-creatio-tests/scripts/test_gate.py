import gate


def test_the_repo_names_are_mapped_to_the_sites_prefix():
    assert gate.mapped("open UsrOrderForm for UsrVisibleRecord", "Abc") == "open AbcOrderForm for AbcVisibleRecord"
    assert gate.mapped("usr-form-visible.act", "Abc") == "abc-form-visible.act"
    assert gate.mapped("Usrx USR_ order", "Abc") == "Usrx USR_ order", "only Usr+Capital and usr- are names"
