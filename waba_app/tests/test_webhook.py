# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

import hashlib
import hmac

from frappe.tests.utils import FrappeTestCase

from waba_app.api.webhook import check_verification
from waba_app.services.signature import compute_signature, verify_signature

SECRET = "test-app-secret"
BODY = b'{"object":"whatsapp_business_account","entry":[]}'


class TestSignature(FrappeTestCase):
	def header(self, body=BODY, secret=SECRET):
		return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

	def test_valid_signature(self):
		self.assertTrue(verify_signature(BODY, self.header(), SECRET))
		self.assertEqual(compute_signature(BODY, SECRET), self.header())

	def test_tampered_body(self):
		self.assertFalse(verify_signature(BODY + b" ", self.header(), SECRET))

	def test_wrong_secret(self):
		self.assertFalse(verify_signature(BODY, self.header(secret="other"), SECRET))

	def test_missing_or_malformed_header(self):
		self.assertFalse(verify_signature(BODY, None, SECRET))
		self.assertFalse(verify_signature(BODY, "", SECRET))
		self.assertFalse(verify_signature(BODY, self.header().removeprefix("sha256="), SECRET))

	def test_no_secret_never_verifies(self):
		self.assertFalse(verify_signature(BODY, self.header(), ""))


class TestVerification(FrappeTestCase):
	def params(self, **overrides):
		values = {"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "1158201444"}
		values.update(overrides)
		return values

	def test_returns_challenge(self):
		self.assertEqual(check_verification(self.params(), "tok"), "1158201444")

	def test_wrong_token(self):
		self.assertIsNone(check_verification(self.params(**{"hub.verify_token": "nope"}), "tok"))

	def test_wrong_mode(self):
		self.assertIsNone(check_verification(self.params(**{"hub.mode": "unsubscribe"}), "tok"))

	def test_unconfigured_token_refuses(self):
		self.assertIsNone(check_verification(self.params(**{"hub.verify_token": ""}), ""))
