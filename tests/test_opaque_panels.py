import pathlib
import re
import unittest

class OpaquePanelSourceTests(unittest.TestCase):
    def test_floating_text_panels_use_shared_opaque_roles(self):
        css=(pathlib.Path(__file__).resolve().parents[1]/'web/styles.css').read_text()
        for selector in ('.mgr-options', '.mgr-jump'):
            with self.subTest(selector=selector):
                match=re.search(re.escape(selector)+r'\s*\{([^}]+)',css)
                assert match is not None, selector
                rule=match.group(1)
                self.assertIn('background:var(--wz-panel-raised,var(--wz-panel,var(--wz-base,var(--canvas))))',rule)
                self.assertNotIn('--wz-surface-raised',rule)

if __name__=='__main__': unittest.main()
