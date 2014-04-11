# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import cint, cstr, flt, formatdate
from frappe import msgprint, _
from erpnext.setup.utils import get_company_currency
import frappe.defaults

from erpnext.controllers.buying_controller import BuyingController

class PurchaseInvoice(BuyingController):
	tname = 'Purchase Invoice Item'
	fname = 'entries'

	def __init__(self, arg1, arg2=None):
		super(PurchaseInvoice, self).__init__(arg1, arg2)
		self.status_updater = [{
			'source_dt': 'Purchase Invoice Item',
			'target_dt': 'Purchase Order Item',
			'join_field': 'po_detail',
			'target_field': 'billed_amt',
			'target_parent_dt': 'Purchase Order',
			'target_parent_field': 'per_billed',
			'target_ref_field': 'amount',
			'source_field': 'amount',
			'percent_join_field': 'purchase_order',
		}]

	def validate(self):
		if not self.is_opening:
			self.is_opening = 'No'

		super(PurchaseInvoice, self).validate()

		self.po_required()
		self.pr_required()
		self.check_active_purchase_items()
		self.check_conversion_rate()
		self.validate_bill_no()
		self.validate_credit_acc()
		self.clear_unallocated_advances("Purchase Invoice Advance", "advance_allocation_details")
		self.check_for_stopped_status()
		self.validate_with_previous_doc()
		self.validate_uom_is_integer("uom", "qty")
		self.set_aging_date()
		self.set_against_expense_account()
		self.validate_write_off_account()
		self.update_raw_material_cost()
		self.update_valuation_rate("entries")
		self.validate_multiple_billing("Purchase Receipt", "pr_detail", "amount",
			"purchase_receipt_details")

	def set_missing_values(self, for_validate=False):
		if not self.credit_to:
			self.credit_to = frappe.db.get_value("Company", self.company, "default_payable_account")
		if not self.due_date:
			from erpnext.contacts.doctype.party.party import get_due_date
			self.due_date = get_due_date(self.posting_date, self.party, self.company)

		super(PurchaseInvoice, self).set_missing_values(for_validate)

	def get_advances(self):
		super(PurchaseInvoice, self).get_advances(self.credit_to, self.party,
			"Purchase Invoice Advance", "advance_allocation_details", "debit")

	def check_active_purchase_items(self):
		for d in self.get('entries'):
			if d.item_code:		# extra condn coz item_code is not mandatory in PV
				valid_item = frappe.db.sql("select docstatus,is_purchase_item from tabItem where name = %s",d.item_code)
				if valid_item[0][0] == 2:
					msgprint("Item : '%s' is Inactive, you can restore it from Trash" %(d.item_code))
					raise Exception
				if not valid_item[0][1] == 'Yes':
					msgprint("Item : '%s' is not Purchase Item"%(d.item_code))
					raise Exception

	def check_conversion_rate(self):
		default_currency = get_company_currency(self.company)
		if not default_currency:
			msgprint('Message: Please enter default currency in Company Master')
			raise Exception
		if (self.currency == default_currency and flt(self.conversion_rate) != 1.00) or not self.conversion_rate or (self.currency != default_currency and flt(self.conversion_rate) == 1.00):
			msgprint("Message: Please Enter Appropriate Conversion Rate.")
			raise Exception

	def validate_bill_no(self):
		if self.bill_no and self.bill_no.lower().strip() \
				not in ['na', 'not applicable', 'none']:
			b_no = frappe.db.sql("""select bill_no, name, ifnull(is_opening,'') from `tabPurchase Invoice`
				where bill_no = %s and credit_to = %s and party=%s and docstatus = 1 and name != %s""",
				(self.bill_no, self.credit_to, self.party, self.name))
			if b_no and cstr(b_no[0][2]) == cstr(self.is_opening):
				msgprint("Please check you have already booked expense against Bill No. %s \
					in Purchase Invoice %s" % (cstr(b_no[0][0]), cstr(b_no[0][1])),
					raise_exception=1)

			if not self.remarks and self.bill_date:
				self.remarks = (self.remarks or '') + "\n" + ("Against Bill %s dated %s"
					% (self.bill_no, formatdate(self.bill_date)))

		if not self.remarks:
			self.remarks = "No Remarks"

	def validate_credit_acc(self):
		if frappe.db.get_value("Account", self.credit_to, "report_type") != "Balance Sheet":
			frappe.throw(_("Account must be a balance sheet account"))

	def check_for_stopped_status(self):
		check_list = []
		for d in self.get('entries'):
			if d.purchase_order and not d.purchase_order in check_list and not d.purchase_receipt:
				check_list.append(d.purchase_order)
				stopped = frappe.db.sql("select name from `tabPurchase Order` where status = 'Stopped' and name = %s", d.purchase_order)
				if stopped:
					msgprint("One cannot do any transaction against 'Purchase Order' : %s, it's status is 'Stopped'" % (d.purhcase_order))
					raise Exception

	def validate_with_previous_doc(self):
		super(PurchaseInvoice, self).validate_with_previous_doc(self.tname, {
			"Purchase Order": {
				"ref_dn_field": "purchase_order",
				"compare_fields": [["party", "="], ["company", "="], ["currency", "="]],
			},
			"Purchase Order Item": {
				"ref_dn_field": "po_detail",
				"compare_fields": [["project_name", "="], ["item_code", "="], ["uom", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True
			},
			"Purchase Receipt": {
				"ref_dn_field": "purchase_receipt",
				"compare_fields": [["party", "="], ["company", "="], ["currency", "="]],
			},
			"Purchase Receipt Item": {
				"ref_dn_field": "pr_detail",
				"compare_fields": [["project_name", "="], ["item_code", "="], ["uom", "="]],
				"is_child_table": True
			}
		})

		if cint(frappe.defaults.get_global_default('maintain_same_rate')):
			super(PurchaseInvoice, self).validate_with_previous_doc(self.tname, {
				"Purchase Order Item": {
					"ref_dn_field": "po_detail",
					"compare_fields": [["rate", "="]],
					"is_child_table": True,
					"allow_duplicate_prev_row_id": True
				},
				"Purchase Receipt Item": {
					"ref_dn_field": "pr_detail",
					"compare_fields": [["rate", "="]],
					"is_child_table": True
				}
			})


	def set_aging_date(self):
		if self.is_opening != 'Yes':
			self.aging_date = self.posting_date
		elif not self.aging_date:
			msgprint("Aging Date is mandatory for opening entry")
			raise Exception

	def set_against_expense_account(self):
		auto_accounting_for_stock = cint(frappe.defaults.get_global_default("auto_accounting_for_stock"))

		if auto_accounting_for_stock:
			stock_not_billed_account = self.get_company_default("stock_received_but_not_billed")

		against_accounts = []
		stock_items = self.get_stock_items()
		for item in self.get("entries"):
			if auto_accounting_for_stock and item.item_code in stock_items \
					and self.is_opening == 'No':
				# in case of auto inventory accounting, against expense account is always
				# Stock Received But Not Billed for a stock item
				item.expense_account = stock_not_billed_account
				item.cost_center = None

				if stock_not_billed_account not in against_accounts:
					against_accounts.append(stock_not_billed_account)

			elif not item.expense_account:
				msgprint(_("Expense account is mandatory for item") + ": " +
					(item.item_code or item.item_name), raise_exception=1)

			elif item.expense_account not in against_accounts:
				# if no auto_accounting_for_stock or not a stock item
				against_accounts.append(item.expense_account)

		self.against_expense_account = ",".join(against_accounts)

	def po_required(self):
		if frappe.db.get_value("Buying Settings", None, "po_required") == 'Yes':
			 for d in self.get('entries'):
				 if not d.purchase_order:
					 msgprint("Purchse Order No. required against item %s"%d.item_code)
					 raise Exception

	def pr_required(self):
		if frappe.db.get_value("Buying Settings", None, "pr_required") == 'Yes':
			 for d in self.get('entries'):
				 if not d.purchase_receipt:
					 msgprint("Purchase Receipt No. required against item %s"%d.item_code)
					 raise Exception

	def validate_write_off_account(self):
		if self.write_off_amount and not self.write_off_account:
			msgprint("Please enter Write Off Account", raise_exception=1)

	def check_prev_docstatus(self):
		for d in self.get('entries'):
			if d.purchase_order:
				submitted = frappe.db.sql("select name from `tabPurchase Order` where docstatus = 1 and name = %s", d.purchase_order)
				if not submitted:
					frappe.throw("Purchase Order : "+ cstr(d.purchase_order) +" is not submitted")
			if d.purchase_receipt:
				submitted = frappe.db.sql("select name from `tabPurchase Receipt` where docstatus = 1 and name = %s", d.purchase_receipt)
				if not submitted:
					frappe.throw("Purchase Receipt : "+ cstr(d.purchase_receipt) +" is not submitted")


	def update_against_document_in_jv(self):
		"""
			Links invoice and advance voucher:
				1. cancel advance voucher
				2. split into multiple rows if partially adjusted, assign against voucher
				3. submit advance voucher
		"""

		lst = []
		for d in self.get('advance_allocation_details'):
			if flt(d.allocated_amount) > 0:
				args = {
					'voucher_no' : d.journal_voucher,
					'voucher_detail_no' : d.jv_detail_no,
					'against_voucher_type' : 'Purchase Invoice',
					'against_voucher'  : self.name,
					'account' : self.credit_to,
					'party': self.party,
					'is_advance' : 'Yes',
					'dr_or_cr' : 'debit',
					'unadjusted_amt' : flt(d.advance_amount),
					'allocated_amt' : flt(d.allocated_amount)
				}
				lst.append(args)

		if lst:
			from erpnext.accounts.utils import reconcile_against_document
			reconcile_against_document(lst)

	def on_submit(self):
		self.check_prev_docstatus()

		frappe.get_doc('Authorization Control').validate_approving_authority(self.doctype,
			self.company, self.grand_total)

		# this sequence because outstanding may get -negative
		self.make_gl_entries()
		self.update_against_document_in_jv()
		self.update_prevdoc_status()
		self.update_billing_status_for_zero_amount_refdoc("Purchase Order")

	def make_gl_entries(self):
		auto_accounting_for_stock = \
			cint(frappe.defaults.get_global_default("auto_accounting_for_stock"))

		gl_entries = []

		# parent's gl entry
		if self.grand_total:
			gl_entries.append(
				self.get_gl_dict({
					"account": self.credit_to,
					"against": self.against_expense_account,
					"credit": self.total_amount_to_pay,
					"party": self.party,
					"remarks": self.remarks,
					"against_voucher": self.name,
					"against_voucher_type": self.doctype,
				})
			)

		# tax table gl entries
		valuation_tax = {}
		for tax in self.get("other_charges"):
			if tax.category in ("Total", "Valuation and Total") and flt(tax.tax_amount):
				gl_entries.append(
					self.get_gl_dict({
						"account": tax.account_head,
						"against": self.credit_to,
						"debit": tax.add_deduct_tax == "Add" and tax.tax_amount or 0,
						"credit": tax.add_deduct_tax == "Deduct" and tax.tax_amount or 0,
						"remarks": self.remarks,
						"cost_center": tax.cost_center
					})
				)

			# accumulate valuation tax
			if tax.category in ("Valuation", "Valuation and Total") and flt(tax.tax_amount):
				if auto_accounting_for_stock and not tax.cost_center:
					frappe.throw(_("Row %(row)s: Cost Center is mandatory \
						if tax/charges category is Valuation or Valuation and Total" %
						{"row": tax.idx}))
				valuation_tax.setdefault(tax.cost_center, 0)
				valuation_tax[tax.cost_center] += \
					(tax.add_deduct_tax == "Add" and 1 or -1) * flt(tax.tax_amount)

		# item gl entries
		stock_item_and_auto_accounting_for_stock = False
		stock_items = self.get_stock_items()
		for item in self.get("entries"):
			if auto_accounting_for_stock and item.item_code in stock_items:
				if flt(item.valuation_rate):
					# if auto inventory accounting enabled and stock item,
					# then do stock related gl entries
					# expense will be booked in sales invoice
					stock_item_and_auto_accounting_for_stock = True

					valuation_amt = flt(item.base_amount + item.item_tax_amount + item.rm_supp_cost,
						self.precision("base_amount", item))

					gl_entries.append(
						self.get_gl_dict({
							"account": item.expense_account,
							"against": self.credit_to,
							"debit": valuation_amt,
							"remarks": self.remarks or "Accounting Entry for Stock"
						})
					)

			elif flt(item.base_amount):
				# if not a stock item or auto inventory accounting disabled, book the expense
				gl_entries.append(
					self.get_gl_dict({
						"account": item.expense_account,
						"against": self.credit_to,
						"debit": item.base_amount,
						"remarks": self.remarks,
						"cost_center": item.cost_center
					})
				)

		if stock_item_and_auto_accounting_for_stock and valuation_tax:
			# credit valuation tax amount in "Expenses Included In Valuation"
			# this will balance out valuation amount included in cost of goods sold
			expenses_included_in_valuation = \
				self.get_company_default("expenses_included_in_valuation")

			for cost_center, amount in valuation_tax.items():
				gl_entries.append(
					self.get_gl_dict({
						"account": expenses_included_in_valuation,
						"cost_center": cost_center,
						"against": self.credit_to,
						"credit": amount,
						"remarks": self.remarks or "Accounting Entry for Stock"
					})
				)

		# writeoff account includes petty difference in the invoice amount
		# and the amount that is paid
		if self.write_off_account and flt(self.write_off_amount):
			gl_entries.append(
				self.get_gl_dict({
					"account": self.write_off_account,
					"against": self.credit_to,
					"credit": flt(self.write_off_amount),
					"remarks": self.remarks,
					"cost_center": self.write_off_cost_center
				})
			)

		if gl_entries:
			from erpnext.accounts.general_ledger import make_gl_entries
			make_gl_entries(gl_entries, cancel=(self.docstatus == 2))

	def on_cancel(self):
		from erpnext.accounts.utils import remove_against_link_from_jv
		remove_against_link_from_jv(self.doctype, self.name, "against_voucher")

		self.update_prevdoc_status()
		self.update_billing_status_for_zero_amount_refdoc("Purchase Order")
		self.make_cancel_gl_entries()

	def on_update(self):
		pass

	def update_raw_material_cost(self):
		if self.sub_contracted_items:
			for d in self.get("entries"):
				rm_cost = frappe.db.sql("""select raw_material_cost / quantity
					from `tabBOM` where item = %s and is_default = 1 and docstatus = 1
					and is_active = 1 """, (d.item_code,))
				rm_cost = rm_cost and flt(rm_cost[0][0]) or 0

				d.conversion_factor = d.conversion_factor or flt(frappe.db.get_value(
					"UOM Conversion Detail", {"parent": d.item_code, "uom": d.uom},
					"conversion_factor")) or 1

				d.rm_supp_cost = rm_cost * flt(d.qty) * flt(d.conversion_factor)

@frappe.whitelist()
def get_expense_account(doctype, txt, searchfield, start, page_len, filters):
	from erpnext.controllers.queries import get_match_cond

	# expense account can be any Debit account,
	# but can also be a Liability account with account_type='Expense Account' in special circumstances.
	# Hence the first condition is an "OR"
	return frappe.db.sql("""select tabAccount.name from `tabAccount`
			where (tabAccount.report_type = "Profit and Loss"
					or tabAccount.account_type = "Expense Account")
				and tabAccount.group_or_ledger="Ledger"
				and tabAccount.docstatus!=2
				and tabAccount.company = '%(company)s'
				and tabAccount.%(key)s LIKE '%(txt)s'
				%(mcond)s""" % {'company': filters['company'], 'key': searchfield,
			'txt': "%%%s%%" % txt, 'mcond':get_match_cond(doctype)})
