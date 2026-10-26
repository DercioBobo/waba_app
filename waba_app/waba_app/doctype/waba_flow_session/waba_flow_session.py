# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

import secrets

import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date, now_datetime

# A customer can only answer a flow inside the 24-hour service window.
SESSION_LIFETIME_HOURS = 24


class WABAFlowSession(Document):
	def before_insert(self):
		if not self.flow_token:
			self.flow_token = new_flow_token()


def new_flow_token() -> str:
	return secrets.token_urlsafe(24)


def expire_stale_sessions() -> None:
	"""Daily: sessions nobody answered within the service window."""
	cutoff = add_to_date(now_datetime(), hours=-SESSION_LIFETIME_HOURS)
	for name in frappe.get_all(
		"WABA Flow Session",
		filters={"status": "Sent", "creation": ["<", cutoff]},
		pluck="name",
	):
		frappe.db.set_value("WABA Flow Session", name, "status", "Expired")
