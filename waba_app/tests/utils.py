# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

import frappe

from waba_app.waba_app.doctype.waba_settings.waba_settings import parse_keywords


class FakeSettings(frappe._dict):
	"""Stands in for WABA Settings so tests never depend on the site's real config."""

	def get_password(self, fieldname, raise_exception=True):
		return self.get(f"_{fieldname}")

	def get_keywords(self, fieldname):
		return parse_keywords(self.get(fieldname))


def make_settings(**overrides) -> FakeSettings:
	values = {
		"enabled": 1,
		"graph_api_version": "v25.0",
		"phone_number_id": "111111111111111",
		"waba_id": "222222222222222",
		"_access_token": "TEST-ACCESS-TOKEN-SECRET",
		"_app_secret": "test-app-secret",
		"verify_token": "test-verify-token",
		"invoice_flow_id": "333333333333333",
		"flow_mode": "draft",
		"invoice_keywords": "facturas,faturas,invoice",
		"test_request_flow_id": "444444444444444",
		"test_request_keywords": "teste,test",
		"company": None,
		"default_country_code": "258",
	}
	values.update(overrides)
	return FakeSettings(values)
