# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import cstr

from frappe import _, msgprint

from erpnext.controllers.selling_controller import SellingController

class Quotation(SellingController):
	tname = 'Quotation Item'
	fname = 'quotation_details'

	def has_sales_order(self):
		return frappe.db.get_value("Sales Order Item", {"prevdoc_docname": self.name, "docstatus": 1})

	def validate_for_items(self):
		chk_dupl_itm = []
		for d in self.get('quotation_details'):
			if [cstr(d.item_code),cstr(d.description)] in chk_dupl_itm:
				msgprint("Item %s has been entered twice. Please change description atleast to continue" % d.item_code)
				raise Exception
			else:
				chk_dupl_itm.append([cstr(d.item_code),cstr(d.description)])

	def validate_order_type(self):
		super(Quotation, self).validate_order_type()

		if self.order_type in ['Maintenance', 'Service']:
			for d in self.get('quotation_details'):
				is_service_item = frappe.db.sql("select is_service_item from `tabItem` where name=%s", d.item_code)
				is_service_item = is_service_item and is_service_item[0][0] or 'No'

				if is_service_item == 'No':
					msgprint("You can not select non service item "+d.item_code+" in Maintenance Quotation")
					raise Exception
		else:
			for d in self.get('quotation_details'):
				is_sales_item = frappe.db.sql("select is_sales_item from `tabItem` where name=%s", d.item_code)
				is_sales_item = is_sales_item and is_sales_item[0][0] or 'No'

				if is_sales_item == 'No':
					msgprint("You can not select non sales item "+d.item_code+" in Sales Quotation")
					raise Exception

	def validate(self):
		super(Quotation, self).validate()
		self.set_status()
		self.validate_order_type()
		self.validate_for_items()
		self.validate_uom_is_integer("stock_uom", "qty")

	def update_opportunity(self):
		for opportunity in list(set([d.prevdoc_docname for d in self.get("quotation_details")])):
			if opportunity:
				frappe.get_doc("Opportunity", opportunity).set_status(update=True)

	def declare_order_lost(self, arg):
		if not self.has_sales_order():
			frappe.db.set(self, 'status', 'Lost')
			frappe.db.set(self, 'order_lost_reason', arg)
			self.update_opportunity()
		else:
			frappe.throw(_("Cannot set as Lost as Sales Order is made."))

	def check_item_table(self):
		if not self.get('quotation_details'):
			msgprint("Please enter item details")
			raise Exception

	def on_submit(self):
		self.check_item_table()

		# Check for Approving Authority
		frappe.get_doc('Authorization Control').validate_approving_authority(self.doctype, self.company, self.grand_total, self)

		#update enquiry status
		self.update_opportunity()

	def on_cancel(self):
		#update enquiry status
		self.set_status()
		self.update_opportunity()

	def print_other_charges(self,docname):
		print_lst = []
		for d in self.get('other_charges'):
			lst1 = []
			lst1.append(d.description)
			lst1.append(d.total)
			print_lst.append(lst1)
		return print_lst


@frappe.whitelist()
def make_sales_order(source_name, target_doc=None):
	return _make_sales_order(source_name, target_doc)

def _make_sales_order(source_name, target_doc=None, ignore_permissions=False):
	from frappe.model.mapper import get_mapped_doc

	party = _make_party(source_name, ignore_permissions)

	def set_missing_values(source, target):
		if party:
			target.party = party.name
			target.party_name = party.party_name

		si = frappe.get_doc(target)
		si.ignore_permissions = ignore_permissions
		si.run_method("onload_post_render")

	doclist = get_mapped_doc("Quotation", source_name, {
			"Quotation": {
				"doctype": "Sales Order",
				"validation": {
					"docstatus": ["=", 1]
				}
			},
			"Quotation Item": {
				"doctype": "Sales Order Item",
				"field_map": {
					"parent": "prevdoc_docname"
				}
			},
			"Sales Taxes and Charges": {
				"doctype": "Sales Taxes and Charges",
				"add_if_empty": True
			},
			"Sales Team": {
				"doctype": "Sales Team",
				"add_if_empty": True
			}
		}, target_doc, set_missing_values, ignore_permissions=ignore_permissions)

	# postprocess: fetch shipping address, set missing values

	return doclist


def _make_party(source_name, ignore_permissions=False):
	quotation = frappe.db.get_value("Quotation", source_name, ["lead", "order_type"])
	if quotation and quotation[0]:
		lead = quotation[0]
		party = frappe.db.get_value("Party", {"lead": lead})
		if not party:
			from erpnext.selling.doctype.lead.lead import _make_party
			party_doclist = _make_party(lead, ignore_permissions=ignore_permissions)
			party = frappe.get_doc(party_doclist)
			party.ignore_permissions = ignore_permissions
			if quotation[1] == "Shopping Cart":
				party.party_group = frappe.db.get_value("Shopping Cart Settings", None,
					"default_customer_group")

			try:
				party.insert()
				return party
			except NameError:
				if frappe.defaults.get_global_default('party_naming_by') == "Party Name":
					party.run_method("autoname")
					party.name += "-" + lead
					party.insert()
					return party
				else:
					raise
			except frappe.MandatoryError:
				from frappe.utils import get_url_to_form
				frappe.throw(_("Before proceeding, please create Customer from Lead") + \
					(" - %s" % get_url_to_form("Lead", lead)))
