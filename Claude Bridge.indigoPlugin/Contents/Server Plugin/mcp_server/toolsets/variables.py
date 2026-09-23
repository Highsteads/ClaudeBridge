#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    variables.py
# Description: Variable tools — list, read, create, update, delete.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from ..registry import tool
from ._schema import id_or_name, number, string


@tool("list_variables", scope="read", cacheable=True, reads={"variable"},
      description="List all variables with id, name, and folder (when not in root)")
def list_variables(ctx):
    return ctx.list_handlers.list_all_variables()


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
