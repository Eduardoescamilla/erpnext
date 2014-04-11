// Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

cur_frm.cscript.refresh = function(doc, cdt, cdn) {
	if(doc.__islocal) {
		msgprint(frappe._("Please create new account from Chart of Accounts."));
		throw "cannot create";
	}

	cur_frm.toggle_display('account_name', doc.__islocal);

	// hide fields if group
	cur_frm.toggle_display(['account_type', 'warehouse', 'tax_rate'], doc.group_or_ledger=='Ledger')

	// disable fields
	cur_frm.toggle_enable(['account_name', 'group_or_ledger', 'company'], false);

	if(doc.group_or_ledger=='Ledger') {
		frappe.model.with_doc("Accounts Settings", "Accounts Settings", function (name) {
			var accounts_settings = frappe.get_doc("Accounts Settings", name);
			var display = accounts_settings["frozen_accounts_modifier"]
				&& in_list(user_roles, accounts_settings["frozen_accounts_modifier"]);

			cur_frm.toggle_display('freeze_account', display);
		});
	}

	// read-only for root accounts
	if(!doc.parent_account) {
		cur_frm.set_read_only();
		cur_frm.set_intro(frappe._("This is a root account and cannot be edited."));
	} else {
		cur_frm.set_intro(null);
		cur_frm.cscript.account_type(doc, cdt, cdn);
		cur_frm.cscript.add_toolbar_buttons(doc);
	}
}

cur_frm.add_fetch('parent_account', 'report_type', 'report_type');

cur_frm.cscript.account_type = function(doc, cdt, cdn) {
	if(doc.group_or_ledger=='Ledger') {
		cur_frm.toggle_display(['tax_rate'], doc.account_type == 'Tax');
		cur_frm.toggle_display('warehouse', doc.account_type=='Warehouse');
	}
}

cur_frm.cscript.add_toolbar_buttons = function(doc) {
	cur_frm.appframe.add_button(frappe._('Chart of Accounts'),
		function() { frappe.set_route("Accounts Browser", "Account"); }, 'icon-sitemap')

	if (cstr(doc.group_or_ledger) == 'Group') {
		cur_frm.add_custom_button(frappe._('Convert to Ledger'),
			function() { cur_frm.cscript.convert_to_ledger(); }, 'icon-retweet')
	} else if (cstr(doc.group_or_ledger) == 'Ledger') {
		cur_frm.add_custom_button(frappe._('Convert to Group'),
			function() { cur_frm.cscript.convert_to_group(); }, 'icon-retweet')

		cur_frm.appframe.add_button(frappe._('View Ledger'), function() {
			frappe.route_options = {
				"account": doc.name,
				"from_date": sys_defaults.year_start_date,
				"to_date": sys_defaults.year_end_date,
				"company": doc.company
			};
			frappe.set_route("query-report", "General Ledger");
		}, "icon-table");
	}
}

cur_frm.cscript.convert_to_ledger = function(doc, cdt, cdn) {
  return $c_obj(cur_frm.doc,'convert_group_to_ledger','',function(r,rt) {
    if(r.message == 1) {
	  cur_frm.refresh();
    }
  });
}

cur_frm.cscript.convert_to_group = function(doc, cdt, cdn) {
  return $c_obj(cur_frm.doc,'convert_ledger_to_group','',function(r,rt) {
    if(r.message == 1) {
	  cur_frm.refresh();
    }
  });
}

cur_frm.fields_dict['parent_account'].get_query = function(doc) {
	return {
		filters: {
			"group_or_ledger": "Group",
			"company": doc.company
		}
	}
}
