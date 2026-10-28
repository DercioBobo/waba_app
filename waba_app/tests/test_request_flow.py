# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

from datetime import date
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from waba_app.services import request_flow as flow

TODAY = date(2026, 10, 28)
PERIODS = ["Manhã", "Tarde", "Noite"]
WA_ID = "258841234567"


def response(**overrides):
	values = {
		"flow_token": "tok",
		"nome": "  Ana   Maria ",
		"categoria": "Comercial",
		"data_preferida": "2026-11-03",
		"periodo": "Tarde",
		"extras": ["ligar", "urgente", "hack"],
		"notas": "  Ligar antes.  ",
		"aceita_contacto": True,
	}
	values.update(overrides)
	return values


class TestValidateRequest(FrappeTestCase):
	def setUp(self):
		self.exists = patch("waba_app.services.request_flow.frappe.db.exists", return_value=True).start()
		self.addCleanup(patch.stopall)

	def validate(self, **overrides):
		return flow.validate_request(response(**overrides), periods=PERIODS, today=TODAY)

	def test_valid_request(self):
		values = self.validate()
		self.assertEqual(
			values,
			{
				"full_name": "Ana Maria",
				"category": "Comercial",
				"period": "Tarde",
				"preferred_date": date(2026, 11, 3),
				"extras": "urgente, ligar",
				"notes": "Ligar antes.",
				"contact_opt_in": 1,
			},
		)
		self.exists.assert_called_once_with(flow.CATEGORY_DOCTYPE, {"name": "Comercial", "enabled": 1})

	def test_optional_fields_missing(self):
		values = self.validate(extras=None, notas=None, aceita_contacto=None)
		self.assertEqual((values["extras"], values["notes"], values["contact_opt_in"]), ("", "", 0))

	def test_missing_name(self):
		for nome in ("", "   ", None, 123):
			with self.subTest(nome=nome), self.assertRaises(flow.InvalidRequest):
				self.validate(nome=nome)

	def test_unknown_or_disabled_category(self):
		self.exists.return_value = False
		with self.assertRaises(flow.InvalidRequest):
			self.validate()

	def test_category_must_be_a_string(self):
		with self.assertRaises(flow.InvalidRequest):
			self.validate(categoria={"$ne": ""})

	def test_invalid_period(self):
		with self.assertRaises(flow.InvalidRequest):
			self.validate(periodo="Madrugada")

	def test_dates(self):
		self.assertEqual(self.validate(data_preferida="2026-10-28")["preferred_date"], TODAY)
		# Older DatePicker versions send epoch milliseconds.
		self.assertEqual(self.validate(data_preferida="1793664000000")["preferred_date"], date(2026, 11, 3))
		for bad in ("2026-10-27", "03/11/2026", "", None, True):
			with self.subTest(data=bad), self.assertRaises(flow.InvalidRequest):
				self.validate(data_preferida=bad)

	def test_long_texts_are_truncated(self):
		values = self.validate(nome="x" * 200, notas="y" * 900)
		self.assertEqual(len(values["full_name"]), flow.MAX_NAME_LENGTH)
		self.assertEqual(len(values["notes"]), flow.MAX_NOTES_LENGTH)


class TestParsers(FrappeTestCase):
	def test_parse_extras(self):
		self.assertEqual(flow.parse_extras(["factura", "urgente", 5]), ["urgente", "factura"])
		self.assertEqual(flow.parse_extras("ligar, urgente"), ["urgente", "ligar"])
		self.assertEqual(flow.parse_extras({"a": 1}), [])

	def test_parse_bool(self):
		self.assertTrue(flow.parse_bool(True))
		self.assertTrue(flow.parse_bool("true"))
		self.assertFalse(flow.parse_bool("false"))
		self.assertFalse(flow.parse_bool(None))
		self.assertFalse(flow.parse_bool(1))


class TestInitialData(FrappeTestCase):
	def test_shape_matches_first_screen(self):
		data = flow.initial_data(["Comercial", "X" * 40], PERIODS, "Ana", TODAY)
		self.assertEqual(set(data), {"nome_sugerido", "categorias", "periodos", "opcoes_extras", "data_minima"})
		self.assertEqual(data["categorias"][0], {"id": "Comercial", "title": "Comercial"})
		self.assertEqual(len(data["categorias"][1]["title"]), flow.MAX_TITLE_LENGTH)
		self.assertEqual(data["categorias"][1]["id"], "X" * 40)
		self.assertEqual(data["data_minima"], "2026-10-28")


class TestOnReply(FrappeTestCase):
	def setUp(self):
		self.reply = patch("waba_app.services.request_flow.reply").start()
		patch("waba_app.services.request_flow.get_periods", return_value=PERIODS).start()
		patch("waba_app.services.request_flow.getdate", return_value=TODAY).start()
		patch("waba_app.services.request_flow.frappe.db.exists", return_value=True).start()
		self.get_doc = patch("waba_app.services.request_flow.frappe.get_doc").start()
		self.get_doc.return_value.insert.return_value = MagicMock(name="WTR-00001", full_name="Ana Maria")
		self.get_doc.return_value.insert.return_value.name = "WTR-00001"
		self.addCleanup(patch.stopall)

	def test_creates_request(self):
		session = MagicMock(customer="CUST-A")
		session.name = "tok"
		self.assertEqual(flow.on_reply(session, response(), WA_ID, "999"), "created")
		doc = self.get_doc.call_args.args[0]
		self.assertEqual(doc["doctype"], flow.REQUEST_DOCTYPE)
		self.assertEqual((doc["wa_id"], doc["customer"], doc["flow_session"]), (WA_ID, "CUST-A", "tok"))
		self.assertEqual(doc["full_name"], "Ana Maria")
		self.assertIn("WTR-00001", self.reply.call_args.args[1])

	def test_invalid_request_is_not_created(self):
		self.assertEqual(flow.on_reply(MagicMock(), response(periodo="?"), WA_ID, "999"), "invalid")
		self.get_doc.assert_not_called()
		self.assertIn("período inválido", self.reply.call_args.args[1])
