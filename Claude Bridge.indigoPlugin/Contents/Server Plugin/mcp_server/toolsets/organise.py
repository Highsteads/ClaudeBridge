#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    organise.py
# Description: Housekeeping across kinds — duplicating objects, moving them
#              between folders, and creating and deleting folders.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from ..registry import tool
from ._schema import FOLDER_ID, bad_choice, boolean, coerce_bool, enum, id_or_name, string

_DUPLICATE = {"device": "duplicate_device", "schedule": "duplicate_schedule",
              "action_group": "duplicate_action_group"}


@tool("duplicate", scope="write", refresh_search=True,
      invalidates={"device", "schedule", "action_group"},
      description=("Duplicate a device, schedule or action group. new_name is optional — "
                   "Indigo defaults to 'Copy of <name>'."),
      properties={
          "kind": enum(list(_DUPLICATE), "What to duplicate"),
          "id": id_or_name("Numeric id of the source"),
          "new_name": string("Optional name for the copy"),
      },
      required=["kind", "id"])
def duplicate(ctx, kind, id, new_name=None):
    if kind not in _DUPLICATE:
        return bad_choice("kind", kind, _DUPLICATE)
    return getattr(ctx.extended_tools_handler, _DUPLICATE[kind])(id, new_name=new_name)


_MOVE = {"device": "move_device_to_folder", "variable": "variable_move_to_folder",
         "trigger": "move_trigger_to_folder"}


@tool("move_to_folder", scope="write", invalidates={"device", "variable", "trigger"},
      description="Move a device, variable or trigger to a different folder. folder_id=0 means root.",
      properties={
          "kind": enum(list(_MOVE), "What to move"),
          "id": id_or_name("Numeric id of the object"),
          "folder_id": FOLDER_ID,
      },
      required=["kind", "id", "folder_id"])
def move_to_folder(ctx, kind, id, folder_id):
    if kind not in _MOVE:
        return bad_choice("kind", kind, _MOVE)
    return getattr(ctx.extended_tools_handler, _MOVE[kind])(id, folder_id)


@tool("create_folder", scope="write", invalidates={"device", "variable"},
      description=("Create a device or variable folder. Returns the existing folder if one with "
                   "the same name already exists (idempotent)."),
      properties={
          "kind": enum(["device", "variable"], "device or variable folder"),
          "name": string("Folder name to create"),
      },
      required=["kind", "name"])
def create_folder(ctx, kind, name):
    if kind not in ("device", "variable"):
        return bad_choice("kind", kind, ("device", "variable"))
    return getattr(ctx.system_tools_handler, f"create_{kind}_folder")(name)


@tool("delete_folder", scope="admin", destructive=True, refresh_search=True,
      invalidates={"device", "variable"},
      description=("Delete a device or variable folder by id or name. Refuses a non-empty "
                   "folder unless delete_children=true, which deletes the devices or variables "
                   "inside it — irreversible."),
      properties={
          "kind": enum(["device", "variable"], "device or variable folder"),
          "folder": id_or_name("Folder id or name"),
          "delete_children": boolean("Also delete the objects inside (default false — a "
                                     "non-empty folder is refused)"),
      },
      required=["kind", "folder"])
def delete_folder(ctx, kind, folder, delete_children=False):
    if kind not in ("device", "variable"):
        return bad_choice("kind", kind, ("device", "variable"))
    return getattr(ctx.system_tools_handler, f"delete_{kind}_folder")(folder, coerce_bool(delete_children))
