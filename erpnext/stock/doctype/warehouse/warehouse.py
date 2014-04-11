# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import cint, validate_email_add
from frappe import throw, msgprint, _
from erpnext.setup.doctype.company.company import get_name_with_abbr

from frappe.model.document import Document

class Warehouse(Document):

	def autoname(self):
		suffix = " - " + frappe.db.get_value("Company", self.company, "abbr")
		if not self.warehouse_name.endswith(suffix):
			self.name = self.warehouse_name + suffix

	def validate(self):
		if self.email_id and not validate_email_add(self.email_id):
				throw(_("Please enter valid Email Id"))

		self.update_parent_account()

	def update_parent_account(self):
		if not getattr(self, "__islocal", None) and (self.create_account_under !=
			frappe.db.get_value("Warehouse", self.name, "create_account_under")):
				warehouse_account = frappe.db.get_value("Account",
					{"account_type": "Warehouse", "company": self.company,
					"warehouse": self.name}, ["name", "parent_account"])
				if warehouse_account and warehouse_account[1] != self.create_account_under:
					acc_doc = frappe.get_doc("Account", warehouse_account[0])
					acc_doc.parent_account = self.create_account_under
					acc_doc.save()

	def on_update(self):
		self.create_account_head()

	def create_account_head(self):
		if cint(frappe.defaults.get_global_default("auto_accounting_for_stock")):
			if not frappe.db.get_value("Account", {"account_type": "Warehouse",
					"warehouse": self.name}) and not frappe.db.get_value("Account",
					{"account_name": self.warehouse_name}):
				if self.get("__islocal") or not frappe.db.get_value(
						"Stock Ledger Entry", {"warehouse": self.name}):
					self.validate_parent_account()
					ac_doc = frappe.get_doc({
						"doctype": "Account",
						'account_name': self.warehouse_name,
						'parent_account': self.create_account_under,
						'group_or_ledger':'Ledger',
						'company':self.company,
						"account_type": "Warehouse",
						"warehouse": self.name,
						"freeze_account": "No"
					})
					ac_doc.ignore_permissions = True
					ac_doc.insert()

					msgprint(_("Account Head") + ": " + ac_doc.name + _(" created"))

	def validate_parent_account(self):
		if not self.create_account_under:
			parent_account = frappe.db.get_value("Account",
				{"account_name": "Stock Assets", "company": self.company})
			if parent_account:
				self.create_account_under = parent_account
			else:
				frappe.throw(_("Please enter account group under which account \
					for warehouse ") + self.name +_(" will be created"))

	def on_trash(self):
		# delete bin
		bins = frappe.db.sql("select * from `tabBin` where warehouse = %s",
			self.name, as_dict=1)
		for d in bins:
			if d['actual_qty'] or d['reserved_qty'] or d['ordered_qty'] or \
					d['indented_qty'] or d['projected_qty'] or d['planned_qty']:
				throw("""Warehouse: %s can not be deleted as qty exists for item: %s"""
					% (self.name, d['item_code']))
			else:
				frappe.db.sql("delete from `tabBin` where name = %s", d['name'])

		warehouse_account = frappe.db.get_value("Account",
			{"account_type": "Warehouse", "warehouse": self.name})
		if warehouse_account:
			frappe.delete_doc("Account", warehouse_account)

		if frappe.db.sql("""select name from `tabStock Ledger Entry`
				where warehouse = %s""", self.name):
			throw(_("""Warehouse can not be deleted as stock ledger entry
				exists for this warehouse."""))

	def before_rename(self, olddn, newdn, merge=False):
		# Add company abbr if not provided
		new_warehouse = get_name_with_abbr(newdn, self.company)

		if merge:
			if not frappe.db.exists("Warehouse", new_warehouse):
				frappe.throw(_("Warehouse ") + new_warehouse +_(" does not exists"))

			if self.company != frappe.db.get_value("Warehouse", new_warehouse, "company"):
				frappe.throw(_("Both Warehouse must belong to same Company"))

			frappe.db.sql("delete from `tabBin` where warehouse=%s", olddn)

		self.rename_account(olddn, newdn, merge, self.company)

		return new_warehouse

	def after_rename(self, olddn, newdn, merge=False):
		if merge:
			self.recalculate_bin_qty(newdn)

	def rename_account(self, olddn, newdn, merge, company):
		old_account = frappe.db.get_value("Account", {"account_type": "Warehouse", "warehouse": olddn})
		if old_account:
			new_account = None
			if not merge:
				if old_account == get_name_with_abbr(olddn, self.company):
					new_account = frappe.rename_doc("Account", old_account, newdn)
			else:
				existing_new_account = frappe.db.get_value("Account",
					{"account_type": "Warehouse", "warehouse": newdn})
				new_account = frappe.rename_doc("Account", old_account, existing_new_account or newdn,
					merge=True if existing_new_account else False)

			frappe.db.set_value("Account", new_account or old_account, "warehouse", newdn)

	def recalculate_bin_qty(self, newdn):
		from erpnext.utilities.repost_stock import repost_stock
		frappe.db.auto_commit_on_many_writes = 1
		frappe.db.set_default("allow_negative_stock", 1)

		for item in frappe.db.sql("""select distinct item_code from (
			select name as item_code from `tabItem` where ifnull(is_stock_item, 'Yes')='Yes'
			union
			select distinct item_code from tabBin) a"""):
				repost_stock(item[0], newdn)

		frappe.db.set_default("allow_negative_stock",
			frappe.db.get_value("Stock Settings", None, "allow_negative_stock"))
		frappe.db.auto_commit_on_many_writes = 0
