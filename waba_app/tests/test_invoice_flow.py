# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from waba_app.services import invoice_flow
from waba_app.tests.utils import make_settings

WA_ID = "258841234567"


class TestOwnership(FrappeTestCase):
	def invoice(self, **overrides):
		values = {
			"name": "SINV-1",
			"customer": "CUST-A",
			"company": "Test Co",
			"docstatus": 1,
			"outstanding_amount": 100.0,
		}
		values.update(overrides)
		return frappe._dict(values)

	def check(self, stored, invoice_name="SINV-1", customer="CUST-A", company=None):
		with patch("waba_app.services.invoice_flow.frappe.db.get_value", return_value=stored):
			return invoice_flow.get_owned_outstanding_invoice(invoice_name, customer, company)

	def test_owned_and_outstanding(self):
		self.assertEqual(self.check(self.invoice()).name, "SINV-1")
		self.assertEqual(self.check(self.invoice(), company="Test Co").name, "SINV-1")

	def test_other_customer(self):
		self.assertIsNone(self.check(self.invoice(customer="CUST-B")))

	def test_not_submitted(self):
		self.assertIsNone(self.check(self.invoice(docstatus=0)))
		self.assertIsNone(self.check(self.invoice(docstatus=2)))

	def test_paid_or_credit(self):
		self.assertIsNone(self.check(self.invoice(outstanding_amount=0)))
		self.assertIsNone(self.check(self.invoice(outstanding_amount=-50)))

	def test_other_company(self):
		self.assertIsNone(self.check(self.invoice(), company="Another Co"))

	def test_missing_or_bad_input(self):
		self.assertIsNone(self.check(None))
		self.assertIsNone(self.check(self.invoice(), invoice_name=None))
		self.assertIsNone(self.check(self.invoice(), invoice_name={"$ne": ""}))
		self.assertIsNone(self.check(self.invoice(), customer=None))


class TestOnReply(FrappeTestCase):
	def setUp(self):
		patch("waba_app.services.invoice_flow.get_settings", return_value=make_settings()).start()
		self.reply = patch("waba_app.services.invoice_flow.reply").start()
		self.perform = patch("waba_app.services.invoice_flow.perform_action", return_value="pdf").start()
		self.addCleanup(patch.stopall)

	def run_reply(self, invoice):
		session = MagicMock(customer="CUST-A")
		response = {"flow_token": "tok", "factura": "SINV-1", "accao": "pdf"}
		with patch("waba_app.services.invoice_flow.get_owned_outstanding_invoice", return_value=invoice) as owned:
			result = invoice_flow.on_reply(session, response, WA_ID, "999")
			owned.assert_called_once_with("SINV-1", "CUST-A", None)
		return result

	def test_owned_invoice_performs_action(self):
		self.assertEqual(self.run_reply(frappe._dict(name="SINV-1")), "pdf")
		self.perform.assert_called_once_with("pdf", "SINV-1", WA_ID, "999")

	def test_invoice_no_longer_owned(self):
		self.assertEqual(self.run_reply(None), "unavailable")
		self.perform.assert_not_called()
		self.reply.assert_called_once_with(WA_ID, invoice_flow.TEXT_UNAVAILABLE, "999")


class TestInvoiceOption(FrappeTestCase):
	def test_shape(self):
		option = invoice_flow.invoice_option(
			{"name": "ACC-SINV-2026-00001", "currency": "MZN", "outstanding_amount": 1250, "due_date": "2026-11-15"}
		)
		self.assertEqual(option["id"], "ACC-SINV-2026-00001")
		self.assertEqual(option["title"], "ACC-SINV-2026-00001")
		self.assertTrue(option["description"].startswith("MZN "))
		self.assertTrue(option["description"].endswith("· vence 15/11/2026"))
