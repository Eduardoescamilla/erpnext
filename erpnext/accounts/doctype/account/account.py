# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import cstr, cint
from frappe import msgprint, throw, _
from frappe.model.document import Document

class Account(Document):
	nsm_parent_field = 'parent_account'

	def autoname(self):
		self.name = self.account_name.strip() + ' - ' + frappe.db.get_value("Company", self.company, "abbr")

	def validate(self):
		self.validate_warehouse()
		self.validate_parent()
		self.validate_duplicate_account()
		self.validate_root_details()
		self.validate_mandatory()
		self.validate_warehouse_account()
		self.validate_frozen_accounts_modifier()

	def validate_warehouse(self):
		if self.account_type == "Warehouse":
			if not self.warehouse:
				msgprint(_("Please enter Warehouse once the account is created."))
			elif not frappe.db.exists("Warehouse", self.warehouse):
				throw(_("Invalid Warehouse linked"))

	def validate_parent(self):
		"""Fetch Parent Details and validation for account not to be created under ledger"""
		if self.parent_account:
			par = frappe.db.get_value("Account", self.parent_account,
				["name", "group_or_ledger", "report_type"], as_dict=1)
			if not par:
				throw(_("Parent account does not exists"))
			elif par["name"] == self.name:
				throw(_("You can not assign itself as parent account"))
			elif par["group_or_ledger"] != 'Group':
				throw(_("Parent account can not be a ledger"))

			if par["report_type"]:
				self.report_type = par["report_type"]

	def validate_duplicate_account(self):
		if self.get('__islocal') or not self.name:
			company_abbr = frappe.db.get_value("Company", self.company, "abbr")
			if frappe.db.exists("Account", (self.account_name + " - " + company_abbr)):
				throw("{name}: {acc_name} {exist}, {rename}".format(**{
					"name": _("Account Name"),
					"acc_name": self.account_name,
					"exist": _("already exists"),
					"rename": _("please rename")
				}))

	def validate_root_details(self):
		#does not exists parent
		if frappe.db.exists("Account", self.name):
			if not frappe.db.get_value("Account", self.name, "parent_account"):
				throw(_("Root cannot be edited."))

	def validate_frozen_accounts_modifier(self):
		old_value = frappe.db.get_value("Account", self.name, "freeze_account")
		if old_value and old_value != self.freeze_account:
			frozen_accounts_modifier = frappe.db.get_value('Accounts Settings',
				None,'frozen_accounts_modifier')
			if not frozen_accounts_modifier or \
				frozen_accounts_modifier not in frappe.user.get_roles():
					throw(_("You are not authorized to set Frozen value"))

	def convert_group_to_ledger(self):
		if self.check_if_child_exists():
			throw("{acc}: {account_name} {child}. {msg}".format(**{
				"acc": _("Account"),
				"account_name": self.name,
				"child": _("has existing child"),
				"msg": _("You can not convert this account to ledger")
			}))
		elif self.check_gle_exists():
			throw(_("Account with existing transaction can not be converted to ledger."))
		else:
			self.group_or_ledger = 'Ledger'
			self.save()
			return 1

	def convert_ledger_to_group(self):
		if self.check_gle_exists():
			throw(_("Account with existing transaction can not be converted to group."))
		elif self.account_type:
			throw(_("Cannot covert to Group because Account Type is selected."))
		else:
			self.group_or_ledger = 'Group'
			self.save()
			return 1

	# Check if any previous balance exists
	def check_gle_exists(self):
		return frappe.db.get_value("GL Entry", {"account": self.name})

	def check_if_child_exists(self):
		return frappe.db.sql("""select name from `tabAccount` where parent_account = %s
			and docstatus != 2""", self.name)

	def validate_mandatory(self):
		if not self.report_type:
			throw(_("Report Type is mandatory"))

	def validate_warehouse_account(self):
		if not cint(frappe.defaults.get_global_default("auto_accounting_for_stock")):
			return

		if self.account_type == "Warehouse":
			old_warehouse = cstr(frappe.db.get_value("Account", self.name, "warehouse"))
			if old_warehouse != cstr(self.warehouse):
				if old_warehouse:
					self.check_if_sle_exists(old_warehouse)
				if self.warehouse:
					self.check_if_sle_exists(self.warehouse)
				else:
					throw(_("Master Name is mandatory if account type is Warehouse"))

	def check_if_sle_exists(self, warehouse):
		if frappe.db.get_value("Stock Ledger Entry", {"warehouse": warehouse}):
			throw(_("Stock transactions exist against warehouse ") + warehouse +
				_(" .You can not assign / modify / remove Master Name"))

	def update_nsm_model(self):
		"""update lft, rgt indices for nested set model"""
		import frappe
		import frappe.utils.nestedset
		frappe.utils.nestedset.update_nsm(self)

	def on_update(self):
		self.update_nsm_model()

	def validate_trash(self):
		"""checks gl entries and if child exists"""
		if not self.parent_account:
			throw(_("Root account can not be deleted"))

		if self.check_gle_exists():
			throw("""Account with existing transaction (Sales Invoice / Purchase Invoice / \
				Journal Voucher) can not be deleted""")
		if self.check_if_child_exists():
			throw(_("Child account exists for this account. You can not delete this account."))

	def on_trash(self):
		self.validate_trash()
		self.update_nsm_model()

	def before_rename(self, old, new, merge=False):
		# Add company abbr if not provided
		from erpnext.setup.doctype.company.company import get_name_with_abbr
		new_account = get_name_with_abbr(new, self.company)

		# Validate properties before merging
		if merge:
			if not frappe.db.exists("Account", new):
				throw(_("Account ") + new +_(" does not exists"))

			val = list(frappe.db.get_value("Account", new_account,
				["group_or_ledger", "report_type", "company"]))

			if val != [self.group_or_ledger, self.report_type, self.company]:
				throw(_("""Merging is only possible if following \
					properties are same in both records.
					Group or Ledger, Report Type, Company"""))

		return new_account

	def after_rename(self, old, new, merge=False):
		if not merge:
			frappe.db.set_value("Account", new, "account_name", " - ".join(new.split(" - ")[:-1]))
		else:
			from frappe.utils.nestedset import rebuild_tree
			rebuild_tree("Account", "parent_account")

def get_parent_account(doctype, txt, searchfield, start, page_len, filters):
	return frappe.db.sql("""select name from tabAccount
		where group_or_ledger = 'Group' and docstatus != 2 and company = %s
		and %s like %s order by name limit %s, %s""" %
		("%s", searchfield, "%s", "%s", "%s"),
		(filters["company"], "%%%s%%" % txt, start, page_len), as_list=1)
