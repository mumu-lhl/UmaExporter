import unittest

from src.core.decryptor import decrypt_bundle


class AssetBundleDecryptionTests(unittest.TestCase):
    def test_region_selects_its_asset_bundle_base_key(self):
        cases = (
            ("jp", 0xFB),
            ("global", 0x53),
        )

        for region, expected_byte in cases:
            with self.subTest(region=region):
                data = bytearray(257)

                decrypt_bundle(data, region=region, key=0)

                self.assertEqual(data[256], expected_byte)

    def test_explicit_base_keys_override_region_default(self):
        data = bytearray(257)

        decrypt_bundle(data, region="jp", key=0, base_keys=bytes([0xAA]))

        self.assertEqual(data[256], 0xAA)


if __name__ == "__main__":
    unittest.main()
