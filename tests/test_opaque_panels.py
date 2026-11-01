import pathlib
import re
import unittest

class OpaquePanelSourceTests(unittest.TestCase):
    def test_outer_frame_fills_host_window(self):
        css=(pathlib.Path(__file__).resolve().parents[1]/'web/styles.css').read_text()
        rule=re.search(r'\.mgr\s*\{([^}]+)',css)
        assert rule is not None
        self.assertIn('width:100%',rule.group(1))
        self.assertNotIn('max-width',rule.group(1))

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
