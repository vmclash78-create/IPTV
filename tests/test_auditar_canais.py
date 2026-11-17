import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "auditar_canais.py"
SPEC = importlib.util.spec_from_file_location("auditar_canais", MODULE_PATH)
auditor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auditor)


class PlaylistParserTests(unittest.TestCase):
    def test_parse_m3u_keeps_name_and_metadata(self):
        text = """#EXTM3U
#EXTINF:-1 tvg-id="canal-1" tvg-logo="https://img.test/logo.png" tvg-country="BR" group-title="Noticias",Canal Teste
https://stream.test/live.m3u8
"""
        parsed = auditor.parse_playlist(text, "fonte-teste")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "Canal Teste")
        self.assertEqual(parsed[0]["tvg_id"], "canal-1")
        self.assertEqual(parsed[0]["group"], "Noticias")
        self.assertEqual(parsed[0]["tvg_country"], "BR")


class SourcePolicyTests(unittest.TestCase):
    def test_official_filter_excludes_community_and_other_countries(self):
        playlist = """#EXTM3U
#EXTINF:-1 tvg-country="BR",Canal Oficial
https://official.test/live.m3u8
#EXTINF:-1 tvg-country="BR" x-tier="community",Canal Comunitario
https://community.test/live.m3u8
#EXTINF:-1 tvg-country="US",Canal Estrangeiro
https://us.test/live.m3u8
"""
        parsed = auditor.parse_playlist(playlist, "Nexonic")
        kept, excluded = auditor.filter_source_entries(
            parsed,
            {"country": "BR", "tier_policy": "official_only", "publish": True, "role": "official_curated"},
        )
        self.assertEqual([item["name"] for item in kept], ["Canal Oficial"])
        self.assertTrue(kept[0]["publishable_source"])
        self.assertEqual(excluded["non_official_tier"], 1)
        self.assertEqual(excluded["wrong_country"], 1)

    def test_rejects_signed_urls_from_publishable_feed(self):
        entry = {
            "name": "Canal Tokenizado",
            "url": "https://cdn.test/live.m3u8?jwt=temporary&includeExtendedEvents=true",
            "tvg_country": "BR",
            "tier": "",
        }
        kept, excluded = auditor.filter_source_entries(
            [entry],
            {"country": "BR", "publish": True, "role": "official_curated"},
        )
        self.assertEqual(kept, [])
        self.assertEqual(excluded["signed_or_credential_url"], 1)

    def test_discovery_source_is_never_publishable(self):
        entry = {
            "name": "Candidato",
            "url": "https://candidate.test/live.m3u8",
            "tvg_country": "BR",
            "tier": "",
        }
        kept, _ = auditor.filter_source_entries(
            [entry],
            {"publish": False, "role": "discovery_only"},
        )
        self.assertFalse(kept[0]["publishable_source"])


class StreamValidationTests(unittest.TestCase):
    def test_rejects_http_200_html(self):
        with patch.object(auditor, "request_bytes", return_value=(b"<html>ok</html>", "https://x.test/a", 200)):
            self.assertFalse(auditor.validate_hls("https://x.test/a")[0])

    def test_accepts_transport_stream_signature(self):
        payload = bytearray(376)
        payload[0] = 0x47
        payload[188] = 0x47
        with patch.object(auditor, "request_bytes", return_value=(bytes(payload), "https://x.test/a.ts", 200)):
            self.assertTrue(auditor.validate_hls("https://x.test/a.ts")[0])

    def test_accepts_hls_manifest_and_ts_segment(self):
        manifest = b"#EXTM3U\n#EXT-X-TARGETDURATION:6\nseg.ts\n#EXT-X-ENDLIST\n"
        segment = bytearray(376)
        segment[0] = 0x47
        segment[188] = 0x47
        def fake_request(url, limit=512_000):
            if url.endswith("index.m3u8"):
                return manifest, url, 200
            return bytes(segment), url, 200
        with patch.object(auditor, "request_bytes", side_effect=fake_request):
            ok, status, _ = auditor.validate_hls("https://x.test/index.m3u8")
        self.assertTrue(ok)
        self.assertEqual(status, "hls_manifest_and_segment_ok")

    def test_resolves_relative_segment_url(self):
        manifest = b"#EXTM3U\nseg.ts\n"
        segment = bytearray(376)
        segment[0] = 0x47
        segment[188] = 0x47
        requested = []
        def fake_request(url, limit=512_000):
            requested.append(url)
            if url.endswith("index.m3u8"):
                return manifest, "https://cdn.test/path/index.m3u8", 200
            return bytes(segment), url, 200
        with patch.object(auditor, "request_bytes", side_effect=fake_request):
            auditor.validate_hls("https://origin.test/index.m3u8")
        self.assertEqual(requested[1], "https://cdn.test/path/seg.ts")


if __name__ == "__main__":
    unittest.main()
