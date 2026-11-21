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


def test_the_real_hosts_of_the_upstream_examples_become_placeholders():
    bundle, identity, ghe = "123" + "-crm-bundle", "c-dev" + "-is", "creatio" + ".ghe.com"  # built, as above
    text = f"{bundle}.creatio.com becomes {bundle}-is.creatio.com; --url https://{identity}.creatio.com; https://{ghe}/team/fb"
    assert placeholder_sites(text) == ("mysite.creatio.com becomes mysite-is.creatio.com; --url https://mysite-is.creatio.com;"
                                       " https://github.com/your-org/clio-feedback")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
