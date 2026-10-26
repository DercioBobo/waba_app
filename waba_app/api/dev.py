# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt
"""Manual triggers for the sandbox. System Manager only."""

import frappe

from waba_app.services.customers import to_wa_id
from waba_app.services.invoice_flow import start_invoice_flow
from waba_app.waba_app.doctype.waba_settings.waba_settings import get_settings


@frappe.whitelist(methods=["POST"])
def send_invoice_flow(phone: str) -> dict:
	"""Sends the invoice Flow to `phone` as if the customer had typed the keyword.

	Free-form messages only reach numbers that wrote to the business in the last 24 hours.
	"""
	frappe.only_for("System Manager")
	wa_id = to_wa_id(phone, get_settings().default_country_code)
	return {"wa_id": wa_id, "result": start_invoice_flow(wa_id)}
