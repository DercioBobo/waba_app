# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt
"""Manual triggers for the sandbox. System Manager only."""

import frappe

from waba_app.services.customers import to_wa_id
from waba_app.services.invoice_flow import start_invoice_flow
from waba_app.services.request_flow import CATEGORY_DOCTYPE, start_test_request_flow
from waba_app.waba_app.doctype.waba_settings.waba_settings import get_settings

TEST_CATEGORIES = ("Suporte técnico", "Comercial", "Facturação")


@frappe.whitelist(methods=["POST"])
def send_invoice_flow(phone: str) -> dict:
	"""Sends the invoice Flow to `phone` as if the customer had typed the keyword.

	Free-form messages only reach numbers that wrote to the business in the last 24 hours.
	"""
	frappe.only_for("System Manager")
	wa_id = to_wa_id(phone, get_settings().default_country_code)
	return {"wa_id": wa_id, "result": start_invoice_flow(wa_id)}


@frappe.whitelist(methods=["POST"])
def send_test_request_flow(phone: str) -> dict:
	"""Same as send_invoice_flow, for the multi-screen test flow."""
	frappe.only_for("System Manager")
	wa_id = to_wa_id(phone, get_settings().default_country_code)
	return {"wa_id": wa_id, "result": start_test_request_flow(wa_id)}


@frappe.whitelist(methods=["POST"])
def seed_test_categories() -> list[str]:
	"""Creates a few WABA Test Categories so the test flow has something to list."""
	frappe.only_for("System Manager")
	created = []
	for category_name in TEST_CATEGORIES:
		if not frappe.db.exists(CATEGORY_DOCTYPE, category_name):
			frappe.get_doc({"doctype": CATEGORY_DOCTYPE, "category_name": category_name, "enabled": 1}).insert()
			created.append(category_name)
	return created
