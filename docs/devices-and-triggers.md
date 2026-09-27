---
title: The device and the trigger
nav_order: 6
---

# The device and the trigger

## The Claude Bridge device

The plugin creates one device for you, called **Claude Bridge**, the first time it starts. You do not need to add it yourself. If you delete it, the plugin makes a new one at its next start, and if you ever want to make one by hand, choose **New Device**, set **Type** to **Claude Bridge** and the model to **Claude Bridge**.

It shows three things:

| State | What it shows |
|---|---|
| **Server Status** | **Running** when the plugin is ready for Claude. **Unavailable** when the plugin started but could not get ready — the Event Log says why. **Stopped** when the plugin, or the device, has been stopped. |
| **Access Mode** | Always **IWS**, meaning Claude reaches the plugin through Indigo's own web server. |
| **Last Activity** | The date and time Claude last used the plugin. It is updated at most once a minute, so a busy session does not fill your history. |

You can use **Server Status** in a trigger, for example to send yourself a notification if it stops saying **Running**, and **Last Activity** on a control page.

The device's own settings have one field, **Server Name**, which is only a label.

## Running a trigger from Claude

The plugin adds one kind of trigger event, **Claude Event**, so a conversation with Claude can set off one of your own triggers — for example "run the sunset routine now", with your trigger doing the work.

1. Create a new trigger and set its type to **Claude Bridge → Claude Event**.
2. Add the actions you want, as for any other trigger.
3. Ask Claude to fire a Claude Event. You can give it a name, such as `sunset_routine`, and some details to pass along.

Every enabled Claude Event trigger is set off each time Claude fires one, which needs a key with the **write** permission. If you have more than one and want each to answer only its own name, add a condition of type **Script** to each trigger that tests the name, for example:

```python
return event_data.get("name") == "sunset_routine"
```

Inside the trigger's actions, Indigo's event-data substitution gives you what Claude sent:

| Substitution | What it holds |
|---|---|
| `%%e:"name"%%` | the event name |
| `%%e:"data"%%` | the details Claude passed along |
| `%%e:"source"%%` | where it came from — `claude` unless Claude says otherwise |

Claude can also run any existing trigger directly by its name or id, without a Claude Event, and run any action group or schedule, with the same permission.

## Actions

The plugin adds no actions of its own to Indigo's action lists. Everything it does, it does when Claude asks.
