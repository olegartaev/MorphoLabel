"""Public documentation requirements, independent of heading wording."""
import re
from app.version import __version__


def assert_public_readme_contract(test,readme):
    lower=readme.lower()
    test.assertRegex(readme,rf'https://github\.com/olegartaev/MorphoLabel/releases/tag/v{re.escape(__version__)}\)')
    test.assertRegex(readme,rf'\[[^\]]+\]\(https://github\.com/olegartaev/MorphoLabel/releases/download/v{re.escape(__version__)}/MorphoLabel-{re.escape(__version__)}-Setup-x64\.exe\)')
    for module in ("landmarks & measurements","x-ray traits"):
        test.assertRegex(lower,rf'(?m)^#+\s+{re.escape(module)}\s*$')
    sections=re.split(r'(?m)^##\s+',lower)
    test.assertTrue(any("data safety" in section.splitlines()[0] and "provenance" in section for section in sections))
    for heading in ("citation","license","release status"):
        test.assertRegex(lower,rf'(?m)^##\s+{heading}\s*$')
    test.assertIn("citation.cff",lower)
    test.assertIn("apache-2.0",lower)
    test.assertIn("release candidate",lower)
