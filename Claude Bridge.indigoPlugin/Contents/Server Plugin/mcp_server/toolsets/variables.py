#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    variables.py
# Description: Variable tools — list, read, create, update, delete.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.1 (3.5.0: list_variables pages; variable_history)

from ..common.paging import paged_reply, paging_args
from ..registry import tool
from ._schema import boolean, coerce_bool, id_or_name, integer, number, refuse, string


@tool("list_variables", scope="read", cacheable=True, reads={"variable"},
      description=("List variables with id, name and folder (when not in root); "
                   "get_variable_by_id gives the value."
                   " Sorted by name, a page at a time: the reply says total, offset, count and next_offset, and offset=next_offset gets the next page until it is null."),
      properties={
          "limit": integer("Page size (default 200, most 1000)"),
          "offset": integer("Where the page starts: 0 for the first, then the next_offset "
                            "the previous page gave (default 0)"),
      })
def list_variables(ctx, limit=None, offset=None):
    off, lim, problem = paging_args(offset, limit, 200)
    if problem:
        return refuse(problem)
    return paged_reply(ctx.list_handlers.list_all_variables(), "variables", off, lim)


@tool("get_variable_by_id", scope="read", cacheable=True, reads={"variable"},
      description="Get a specific variable by ID",
      properties={"variable_id": id_or_name("The variable ID")},
      required=["variable_id"])
def get_variable_by_id(ctx, variable_id):
    variable_id = int(variable_id)
    variable = ctx.data_provider.get_variable(variable_id)
    if variable is None:
        return {"error": f"Variable {variable_id} not found"}
    return variable


@tool("variable_history", scope="read",
      description=("One variable's history from the SQLite SQL Logger (a PostgreSQL SQL "
                   "Logger is not read). The logger writes a row only when the value changes, "
                   "so the reply also gives value_before: the value in force when the window "
                   "opened. Rows are newest first with ts in local time; limit caps them from "
                   "the newest end, so check truncated and ts_oldest. summary=true instead "
                   "gives the number of changes and, per distinct value, how often it was set "
                   "and how long it held in the window (share_of_window), plus min, max and a "
                   "time-weighted mean when every value is a number — the way to answer 'how "
                   "long was it true today'. A deleted variable's history can still be read by "
                   "its old id."),
      properties={
          "variable": id_or_name("The variable: its id, or its exact name (a name is matched "
                                 "ignoring case if there is no exact match)"),
          "hours": number("Lookback in hours (default 24, most 744 = 31 days)"),
          "limit": integer("Most rows, newest first (default 500, most 5000); not used with "
                           "summary"),
          "summary": boolean("Instead of rows: changes, time held per value and numeric "
                             "stats (default false)"),
      },
      required=["variable"])
def variable_history(ctx, variable, hours=24, limit=500, summary=False):
    vid, name, problem = _resolve_variable(ctx, variable)
    if problem:
        return refuse(problem)
    return ctx.plugin_dev_tools_handler.variable_history(
        vid, hours=hours, limit=limit, summary=coerce_bool(summary), name=name)


def _resolve_variable(ctx, variable):
    """(id, name, problem). A whole number is an id, kept even when no current
    variable has it: the SQL Logger keeps a deleted variable's table. Otherwise
    an exact name, then one that matches ignoring case."""
    if isinstance(variable, bool):
        return None, None, "variable must be an id or a name"
    text = str(variable).strip()
    if not text:
        return None, None, "variable is empty"
    rows = ctx.data_provider.get_all_variables() or []
    if text.lstrip("-").isdigit():
        vid = int(text)
        name = next((r.get("name") for r in rows if r.get("id") == vid), None)
        return vid, name, None
    exact = [r for r in rows if r.get("name") == text]
    if not exact:
        exact = [r for r in rows if str(r.get("name", "")).lower() == text.lower()]
    if len(exact) == 1:
        return exact[0].get("id"), exact[0].get("name"), None
    if exact:
        ids = ", ".join(str(r.get("id")) for r in exact)
        return None, None, f"{len(exact)} variables are called {text!r} (ids {ids}); give the id"
    return None, None, f"No variable called {text!r}; list_variables or search_entities finds it"


@tool("list_variable_folders", scope="read", cacheable=True, reads={"variable"},
      description="List all variable folders for organization")
def list_variable_folders(ctx):
    return ctx.list_handlers.list_variable_folders()


@tool("variable_update", scope="write", invalidates={"variable"},
      description="Update a variable's value",
      properties={"variable_id": id_or_name("The ID of the variable"),
                  "value": string("The new value for the variable")},
      required=["variable_id", "value"])
def variable_update(ctx, variable_id, value):
    return ctx.variable_control_handler.update(variable_id, value)


@tool("variable_create", scope="write", invalidates={"variable"}, refresh_search=True,
      description="Create a new variable",
      properties={
          "name": string("The name of the variable (required)"),
          "value": string("Initial value for the variable (optional, defaults to empty string)"),
          "folder_id": number("Folder ID for organization (optional, defaults to 0 = root)"),
      },
      required=["name"])
def variable_create(ctx, name, value="", folder_id=0):
    return ctx.variable_control_handler.create(name, value, folder_id)


@tool("variable_delete", scope="admin", invalidates={"variable"}, refresh_search=True,
      destructive=True,
      description="Permanently delete a variable. Destructive — cannot be undone.",
      properties={"variable_id": id_or_name("The variable ID")},
      required=["variable_id"])
def variable_delete(ctx, variable_id):
    return ctx.extended_tools_handler.variable_delete(variable_id)
