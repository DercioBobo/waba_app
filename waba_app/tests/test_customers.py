# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from waba_app.services.customers import (
	find_customer_by_phone,
	local_part,
	normalize_phone,
	phones_match,
	to_wa_id,
)

CC = "258"
WA_ID = "258841234567"


class TestPhoneNormalization(FrappeTestCase):
	def test_normalize_strips_formatting_and_00(self):
		self.assertEqual(normalize_phone("+258 84 123 4567"), "258841234567")
		self.assertEqual(normalize_phone("00258-84-123-4567"), "258841234567")
		self.assertEqual(normalize_phone("(84) 123.4567"), "841234567")
		self.assertEqual(normalize_phone(None), "")

	def test_local_part(self):
		self.assertEqual(local_part("258841234567", CC), "841234567")
		self.assertEqual(local_part("841234567", CC), "841234567")
		self.assertEqual(local_part("0841234567", CC), "841234567")
		# An 8-digit landline that happens to start with 258 keeps its digits.
		self.assertEqual(local_part("25812345", CC), "25812345")

	def test_stored_formats_match_wa_id(self):
		for stored in (
			"+258 84 123 4567",
			"258841234567",
			"00258841234567",
			"841234567",
			"84 123 4567",
			"084 123 4567",
			"+258-84-123-4567",
		):
			with self.subTest(stored=stored):
				self.assertTrue(phones_match(stored, WA_ID, CC))

	def test_different_numbers_do_not_match(self):
		self.assertFalse(phones_match("841234568", WA_ID, CC))
		self.assertFalse(phones_match("+27 84 123 4567", WA_ID, CC))
		self.assertFalse(phones_match("", WA_ID, CC))
		self.assertFalse(phones_match("4567", "4567", CC))

	def test_foreign_number_matches_itself(self):
		self.assertTrue(phones_match("+27 82 123 4567", "27821234567", CC))

	def test_to_wa_id(self):
		self.assertEqual(to_wa_id("84 123 4567", CC), WA_ID)
		self.assertEqual(to_wa_id("+258 84 123 4567", CC), WA_ID)
		self.assertEqual(to_wa_id("258841234567", CC), WA_ID)
		self.assertEqual(to_wa_id("+27 82 123 4567", CC), "27821234567")


class TestFindCustomer(FrappeTestCase):
	def rows(self, *pairs):
		return [frappe._dict(customer=customer, phone=phone) for customer, phone in pairs]

	def test_single_customer(self):
		with patch(
			"waba_app.services.customers._candidate_rows",
			return_value=self.rows(("CUST-A", "+258 84 123 4567"), ("CUST-A", "841234567")),
		) as candidates:
			self.assertEqual(find_customer_by_phone(WA_ID, CC), "CUST-A")
			candidates.assert_called_once_with("1234567")

	def test_suffix_collision_is_filtered_out(self):
		with patch(
			"waba_app.services.customers._candidate_rows",
			return_value=self.rows(("CUST-A", "841234567"), ("CUST-B", "+258 82 123 4567")),
		):
			self.assertEqual(find_customer_by_phone(WA_ID, CC), "CUST-A")

	def test_multiple_customers_picks_none(self):
		with patch(
			"waba_app.services.customers._candidate_rows",
			return_value=self.rows(("CUST-A", "841234567"), ("CUST-B", "+258841234567")),
		):
			self.assertIsNone(find_customer_by_phone(WA_ID, CC))

	def test_no_match(self):
		with patch("waba_app.services.customers._candidate_rows", return_value=[]):
			self.assertIsNone(find_customer_by_phone(WA_ID, CC))

	def test_too_short_number_skips_query(self):
		with patch("waba_app.services.customers._candidate_rows") as candidates:
			self.assertIsNone(find_customer_by_phone("258123", CC))
			candidates.assert_not_called()
