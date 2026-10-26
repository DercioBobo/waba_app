# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt
"""Matches a WhatsApp number (digits with country code, e.g. 258841234567) to a Customer.

ERPNext contacts store numbers in any shape: '+258 84 123 4567', '841234567',
'00258...'. Both sides are reduced to their national part and compared.
"""

import re

import frappe

from waba_app.waba_app.doctype.waba_settings.waba_settings import get_settings

# Shortest national number we are willing to match on.
MIN_LOCAL_DIGITS = 7
# The SQL pre-filter compares the last digits only; Python makes the final call.
SUFFIX_DIGITS = 7


def normalize_phone(raw: str | None) -> str:
	"""Digits only, without the international '00' prefix."""
	digits = re.sub(r"\D", "", raw or "")
	if digits.startswith("00"):
		digits = digits[2:]
	return digits


def local_part(raw: str | None, country_code: str) -> str:
	"""The national number: country code and trunk zeros removed."""
	digits = normalize_phone(raw)
	if country_code and digits.startswith(country_code) and len(digits) >= len(country_code) + MIN_LOCAL_DIGITS:
		digits = digits[len(country_code) :]
	return digits.lstrip("0")


def phone_variants(raw: str | None, country_code: str) -> set[str]:
	"""Digit-only spellings of the same number, with and without the country code."""
	local = local_part(raw, country_code)
	if not local:
		return set()
	return {local, f"0{local}", f"{country_code}{local}", f"00{country_code}{local}"}


def phones_match(stored: str | None, wa_id: str, country_code: str) -> bool:
	local = local_part(wa_id, country_code)
	if len(local) < MIN_LOCAL_DIGITS:
		return False
	return normalize_phone(stored) in phone_variants(wa_id, country_code)


def to_wa_id(phone: str, country_code: str) -> str:
	"""A number typed by a person -> the digits-only international form WhatsApp uses."""
	explicit_international = phone.strip().startswith(("+", "00"))
	digits = normalize_phone(phone)
	if explicit_international or (digits.startswith(country_code) and len(digits) >= len(country_code) + MIN_LOCAL_DIGITS):
		return digits
	return f"{country_code}{digits.lstrip('0')}"


def find_customer_by_phone(wa_id: str, country_code: str | None = None) -> str | None:
	"""The single enabled Customer linked to a Contact with this number, else None."""
	country_code = country_code or get_settings().default_country_code
	local = local_part(wa_id, country_code)
	if len(local) < MIN_LOCAL_DIGITS:
		return None

	customers = {
		row.customer
		for row in _candidate_rows(local[-SUFFIX_DIGITS:])
		if phones_match(row.phone, wa_id, country_code)
	}
	if len(customers) == 1:
		return customers.pop()
	if len(customers) > 1:
		frappe.logger("waba_app").warning(f"WABA: {wa_id} matches several customers {sorted(customers)}; none selected")
	return None


def _digits_sql(column: str) -> str:
	expr = column
	for char in (" ", "+", "-", "(", ")", ".", "/"):
		expr = f"replace({expr}, '{char}', '')"
	return expr


def _candidate_rows(suffix: str) -> list:
	"""(customer, phone) rows whose number ends with `suffix`, from Contact Phone and Contact.mobile_no."""
	link_join = """
		inner join `tabDynamic Link` dl
			on dl.parent = c.name and dl.parenttype = 'Contact' and dl.link_doctype = 'Customer'
		inner join `tabCustomer` cu on cu.name = dl.link_name and cu.disabled = 0
	"""
	return frappe.db.sql(
		f"""
		select dl.link_name as customer, cp.phone as phone
		from `tabContact Phone` cp
		inner join `tabContact` c on c.name = cp.parent and cp.parenttype = 'Contact'
		{link_join}
		where {_digits_sql("cp.phone")} like %(suffix)s
		union all
		select dl.link_name as customer, c.mobile_no as phone
		from `tabContact` c
		{link_join}
		where {_digits_sql("c.mobile_no")} like %(suffix)s
		""",
		{"suffix": f"%{suffix}"},
		as_dict=True,
	)
