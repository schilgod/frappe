# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals
import frappe, os, time

from frappe import _
from frappe.utils import cint
from markdown2 import markdown

def sync_statics():
	s = sync()
	while True:
		s.start()
		frappe.conn.commit()
		time.sleep(2)

class sync(object):
	def __init__(self):
		self.synced = []

	def start(self):
		for app in frappe.get_installed_apps():
			self.sync_for_app(app)

		self.cleanup()
		print "sync complete"
		
	def sync_for_app(self, app):
		self.statics_path = frappe.get_app_path(app, "templates", "statics")
		if os.path.exists(self.statics_path):
			for basepath, folders, files in os.walk(self.statics_path):
				self.sync_folder(basepath, folders, files)

				
	def sync_folder(self, basepath, folders, files):
		self.has_index = False
		self.get_index_txt(basepath, files)

		if basepath!=self.statics_path:
			self.sync_index_page(basepath, files)
		
			if not self.has_index: # index.md or index.html is required, else skip
				return
				
			if self.index:
				self.sync_using_given_index(basepath, folders, files)
				
			else:
				self.sync_alphabetically(basepath, folders, files)
				
		
	def get_index_txt(self, basepath, files):
		self.index = []
		if "index.txt" in files:
			with open(os.path.join(basepath, "index.txt"), "r") as indexfile:
				self.index = indexfile.read().splitlines()

	def sync_index_page(self, basepath, files):
		for extn in ("md", "html"):
			fname = "index." + extn
			if fname in files:
				self.sync_file(fname, os.path.join(basepath, fname), None)
				self.has_index = True
				return
		
	def sync_using_given_index(self, basepath, folders, files):
		for i, page_name in enumerate(self.index):
			if page_name in folders:
				# for folder, sync inner index first (so that idx is set)
				for extn in ("md", "html"):
					path = os.path.join(basepath, page_name, "index." + extn)
					if os.path.exists(path):
						self.sync_file("index." + extn, path, i)
						break

			# other files
			for extn in ("md", "html"):
				fname = page_name + "." + extn
				if fname in files:
					self.sync_file(fname, os.path.join(basepath, fname), i)
					break
				elif page_name not in folders:
					print page_name + " not found in " + basepath

	def sync_alphabetically(self, basepath, folders, files):
		files.sort()
		for fname in files:
			page_name = fname.rsplit(".", 1)[0]
			if not (page_name=="index" and basepath!=self.statics_path):
				self.sync_file(fname, os.path.join(basepath, fname), None)
		
	def sync_file(self, fname, fpath, priority):
		route = os.path.relpath(fpath, self.statics_path).rsplit(".", 1)[0]

		if fname.rsplit(".", 1)[0]=="index" and os.path.dirname(fpath) != self.statics_path:
			route = os.path.dirname(route)
	
		if route in self.synced:
			return
	
		parent_website_route = os.path.dirname(route)
		page_name = os.path.basename(route)
			
		try:
			route_bean = frappe.bean("Website Route", route)
		except frappe.DoesNotExistError:
			# Route does not exist, new page
			self.insert_web_page(route, fpath, page_name, priority, parent_website_route)
		else:
			self.update_web_page(route, route_bean, fpath, priority)
		return None

	def insert_web_page(self, route, fpath, page_name, priority, parent_website_route):
		title, content = get_static_content(fpath)
		if not title:
			title = page_name.replace("-", " ").replace("_", " ").title()
		page = frappe.bean({
			"doctype":"Web Page",
			"idx": priority,
			"title": title,
			"page_name": page_name,
			"main_section": content,
			"published": 1,
			"parent_website_route": parent_website_route
		})

		try:
			page.insert()
		except NameError:
			# page exists, if deleted static, delete it and try again
			old_route = frappe.doc("Website Route", {"ref_doctype":"Web Page", 
				"docname": page.doc.name})
			if old_route.static_file_timestamp and not os.path.exists(os.path.join(self.statics_path, 
				old_route.name)):
				
				frappe.delete_doc("Web Page", page.doc.name)
				page.insert() # retry
				
		# update timestamp
		route_bean = frappe.bean("Website Route", {"ref_doctype": "Web Page", 
			"docname": page.doc.name})
		route_bean.doc.static_file_timestamp = os.path.getmtime(fpath)
		route_bean.save()

		self.synced.append(route)
	
	def update_web_page(self, route, route_bean, fpath, priority):
		if str(os.path.getmtime(fpath))!=route_bean.doc.static_file_timestamp \
			or cint(route_bean.doc.idx) != cint(priority):

			page = frappe.bean("Web Page", route_bean.doc.docname)
			title, content = get_static_content(fpath)
			page.doc.main_section = content
			page.doc.idx = priority
			if not title:
				title = route_bean.doc.docname.replace("-", " ").replace("_", " ").title()
			page.doc.title = title
			page.save()

			route_bean = frappe.bean("Website Route", route)
			route_bean.doc.static_file_timestamp = os.path.getmtime(fpath)
			route_bean.save()

			self.synced.append(route)

	def cleanup(self):
		if self.synced:
			frappe.delete_doc("Web Page", frappe.conn.sql_list("""select docname 
				from `tabWebsite Route`
				where ifnull(static_file_timestamp,'')!='' and name not in ({}) 
				order by (rgt-lft) asc""".format(', '.join(["%s"]*len(self.synced))), 
					tuple(self.synced)))
		else:
			frappe.delete_doc("Web Page", frappe.conn.sql_list("""select docname 
				from `tabWebsite Route`
				where ifnull(static_file_timestamp,'')!='' 
				order by (rgt-lft) asc"""))


def get_static_content(fpath):
	with open(fpath, "r") as contentfile:
		title = None
		content = unicode(contentfile.read(), 'utf-8')

		if fpath.endswith(".md"):
			if content:
				lines = content.splitlines()
				first_line = lines[0].strip()

				if first_line.startswith("# "):
					title = first_line[2:]
					content = "\n".join(lines[1:])

				content = markdown(content)
			
		content = unicode(content.encode("utf-8"), 'utf-8')
			
		return title, content