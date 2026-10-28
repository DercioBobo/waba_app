# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


class WABASettings(Document):
	def validate(self):
		self.graph_api_version = (self.graph_api_version or "").strip()
		if not re.fullmatch(r"v\d+\.\d+", self.graph_api_version):
			frappe.throw(_("Graph API Version must look like v25.0"))

		self.default_country_code = re.sub(r"\D", "", self.default_country_code or "")
		if not self.default_country_code:
			frappe.throw(_("Default Country Code must contain digits"))

		for fieldname in ("phone_number_id", "waba_id", "verify_token", "invoice_flow_id", "test_request_flow_id"):
			self.set(fieldname, (self.get(fieldname) or "").strip())

		for fieldname in KEYWORD_FIELDS:
			self.set(fieldname, ",".join(sorted(parse_keywords(self.get(fieldname)))))

	def get_keywords(self, fieldname: str) -> set[str]:
		return parse_keywords(self.get(fieldname))


KEYWORD_FIELDS = ("invoice_keywords", "test_request_keywords")


def parse_keywords(text: str | None) -> set[str]:
	"""'Facturas, faturas ,INVOICE' -> {'facturas', 'faturas', 'invoice'}"""
	return {word.strip().casefold() for word in (text or "").split(",") if word.strip()}


def get_settings() -> WABASettings:
	return frappe.get_cached_doc("WABA Settings")
