"""Checks for the clio reference generator:  python no-code/tools/tests/test_sync_clio_docs.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sync_clio_docs import placeholder_sites  # noqa: E402


def test_numbered_site_names_become_placeholders():
    two, three = "Dev" + "2", "dev" + "3"  # built, so the file itself holds no such name
    text = f'clio deploy-creatio --site-name "{two}" --db pg\nclio x --site-name {three}\nDev and DevSecond and devops stay'
    assert placeholder_sites(text) == ('clio deploy-creatio --site-name "DevSecond" --db pg\nclio x --site-name devOther\n'
                                       'Dev and DevSecond and devops stay')


if __name__ == "__main__":
    test_numbered_site_names_become_placeholders()
    print("ok test_numbered_site_names_become_placeholders")
