# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe

from frappe import msgprint, throw, _
from frappe.utils import cstr, cint

from frappe.model.document import Document

class Address(Document):
	def autoname(self):
		if not self.address_title:
			self.address_title = self.party or self.lead

		if self.address_title:
			self.name = cstr(self.address_title).strip() + "-" + cstr(self.address_type).strip()
		else:
			throw(_("Address Title is mandatory."))

	def validate(self):
		self.validate_primary_address()
		self.validate_shipping_address()

	def validate_primary_address(self):
		"""Validate that there can only be one primary address for particular party"""
		if self.is_primary_address == 1:
			self._unset_other("is_primary_address")

		elif self.is_shipping_address != 1:
			for fieldname in ["party", "lead"]:
				if self.get(fieldname):
					if not frappe.db.sql("""select name from `tabAddress` where is_primary_address=1
						and `%s`=%s and name!=%s""" % (fieldname, "%s", "%s"),
						(self.get(fieldname), self.name)):
							self.is_primary_address = 1
					break

	def validate_shipping_address(self):
		"""Validate that there can only be one shipping address for particular party"""
		if self.is_shipping_address == 1:
			self._unset_other("is_shipping_address")

	def _unset_other(self, is_address_type):
		for fieldname in ["party", "lead"]:
			if self.get(fieldname):
				frappe.db.sql("""update `tabAddress` set `%s`=0 where `%s`=%s and name!=%s""" %
					(is_address_type, fieldname, "%s", "%s"), (self.get(fieldname), self.name))
				break

@frappe.whitelist()
def get_address_display(address_dict):
	if not isinstance(address_dict, dict):
		address_dict = frappe.db.get_value("Address", address_dict, "*", as_dict=True) or {}

	meta = frappe.get_meta("Address")
	sequence = (("", "address_line1"),
		("\n", "address_line2"),
		("\n", "city"),
		("\n", "state"),
		("\n" + meta.get_label("pincode") + ": ", "pincode"),
		("\n", "country"),
		("\n" + meta.get_label("phone") + ": ", "phone"),
		("\n" + meta.get_label("fax") + ": ", "fax"))

	display = ""
	for separator, fieldname in sequence:
		if address_dict.get(fieldname):
			display += separator + address_dict.get(fieldname)

	return display.strip()

