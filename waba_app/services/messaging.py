# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

import frappe

from waba_app.services.whatsapp import WhatsAppAPIError, send_text


def reply(
	wa_id: str,
	body: str,
	phone_number_id: str | None = None,
	*,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> bool:
	"""Best-effort text reply. Failures are logged, never raised to the caller."""
	try:
		send_text(
			wa_id,
			body,
			phone_number_id=phone_number_id,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
		)
		return True
	except WhatsAppAPIError:
		return False  # Already in WABA Message Log.
	except Exception:
		frappe.log_error(title="WABA: reply failed")
		return False
