import io
import json
import unittest
from app.release_update_check import version_key,newer_release,check_for_release


def release(version="v1.0.0",**kw):
    return {"tag_name":version,
            "html_url":"https://github.com/olegartaev/MorphoLabel/releases/tag/"+version,
            "body":"Fix crop navigation and update the documentation.",**kw}


class ReleaseUpdateTests(unittest.TestCase):
    def test_release_order(self):
        self.assertLess(version_key("1.0.0-rc.1"),version_key("v1.0.0"))
        self.assertGreater(version_key("v1.1.0"),version_key("1.0.0"))
        self.assertIsNone(version_key("not_a_version"))
    def test_read_only_update_notice(self):
        info=newer_release("1.0.0-rc.1",release())
        self.assertIn("1.0.0",info["version"])
        self.assertIn("documentation",info["changes"])
    def test_older_draft_and_untrusted_link(self):
        self.assertIsNone(newer_release("v1.1.0",release("v1.0.0")))
        self.assertIsNone(newer_release("1.0.0-rc.1",release(draft=True)))
        self.assertIsNone(newer_release("1.0.0-rc.1",release(prerelease=True)))
        m=release();m["html_url"]="https://example.com/install.exe"
        self.assertIsNone(newer_release("1.0.0-rc.1",m))
    def test_http_mock(self):
        class Stream(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        def fake(req,timeout):
            self.assertEqual(timeout,4)
            self.assertEqual(req.full_url,"https://api.github.com/repos/olegartaev/MorphoLabel/releases/latest")
            return Stream(json.dumps(release()).encode("utf-8"))
        self.assertIsNotNone(check_for_release("1.0.0-rc.1",fake))

if __name__=="__main__": unittest.main()
