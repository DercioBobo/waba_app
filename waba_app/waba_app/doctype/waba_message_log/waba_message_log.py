# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class WABAMessageLog(Document):
	def validate(self):
		# wamid is unique: an empty string would collide, NULL does not.
		self.wamid = (self.wamid or "").strip() or None
