#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    notify.py
# Description: Telling people things — Pushover, email and the event log.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from ..registry import tool
from ._schema import enum, string


# send_notification stays a write: Pushover delivers only to the devices on the
# owner's own Pushover account, set in Indigo, so the caller cannot choose where
# it goes. send_email is admin: it sends to any address the caller names, and
# data leaving the house is admin.
@tool("send_notification", scope="write", sensitive=True,
      description=("Send a Pushover push notification to the user's own devices (the Pushover "
                   "account set up in Indigo; the caller cannot choose another recipient). Use "
                   "for important alerts, confirmations, or proactive updates."),
      properties={
          "title": string("Notification title"),
          "message": string("Notification body text"),
          "priority": enum(["-2", "-1", "0", "1"],
                           "Priority: -2=silent, -1=quiet, 0=normal (default), 1=high"),
          "sound": string("Notification sound (default 'vibrate')"),
      },
      required=["title", "message"])
def send_notification(ctx, title, message, priority="0", sound="vibrate"):
    return ctx.data_provider.send_notification(title, message, priority, sound)


@tool("send_email", scope="admin", sensitive=True,
      description=("Send an email via Indigo's configured SMTP device to any address. Use for "
                   "detailed reports, logs, or non-urgent notifications. ADMIN scope: it sends "
                   "data out of the house to a recipient the caller chooses."),
      properties={
          "recipient": string("Recipient email address"),
          "subject": string("Email subject line"),
          "body": string("Email body text (plain text or HTML)"),
      },
      required=["recipient", "subject", "body"])
def send_email(ctx, recipient, subject, body):
    return ctx.data_provider.send_email(recipient, subject, body)


@tool("log_message", scope="write",
      description=("Write a message to the Indigo on-screen event log (Log Viewer). The message "
                   "appears immediately. Use for status updates, confirmations, or debug output "
                   "that the user can see in the Indigo UI."),
      properties={
          "message": string("Message text to log"),
          "level": enum(["INFO", "WARNING", "ERROR", "DEBUG"], "Log level (default INFO)"),
      },
      required=["message"])
def log_message(ctx, message, level="INFO"):
    return ctx.script_tools_handler.log_message(message, level)
