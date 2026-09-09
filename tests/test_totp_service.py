import unittest

import pyotp

from services.totp_service import normalize_totp_code, verify_totp_code


class TotpServiceTests(unittest.TestCase):
    def setUp(self):
        self.secret = pyotp.random_base32()
        self.timestamp = 1_700_000_000
        self.totp = pyotp.TOTP(self.secret, digits=6, interval=30)

    def test_normalize_requires_exact_ascii_six_digits(self):
        self.assertEqual(normalize_totp_code(' 012345 '), '012345')
        self.assertIsNone(normalize_totp_code('12345'))
        self.assertIsNone(normalize_totp_code('1234567'))
        self.assertIsNone(normalize_totp_code('12 3456'))
        self.assertIsNone(normalize_totp_code('１２３４５６'))

    def test_verify_accepts_current_code_and_one_interval_of_clock_drift(self):
        current_code = self.totp.at(self.timestamp)
        previous_code = self.totp.at(self.timestamp - 30)

        self.assertTrue(verify_totp_code(self.secret, current_code, for_time=self.timestamp))
        self.assertTrue(verify_totp_code(self.secret, previous_code, for_time=self.timestamp))

    def test_verify_rejects_malformed_or_expired_codes(self):
        expired_code = self.totp.at(self.timestamp - 60)

        self.assertFalse(verify_totp_code(self.secret, '12345', for_time=self.timestamp))
        self.assertFalse(verify_totp_code(self.secret, expired_code, for_time=self.timestamp))


if __name__ == '__main__':
    unittest.main()
