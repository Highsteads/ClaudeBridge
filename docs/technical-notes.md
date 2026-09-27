---
title: Technical notes
nav_order: 11
has_children: true
---

# Technical notes

These pages are for anyone who wants the full detail: the name of every tool, exactly what each permission allows, how to make your own plugin add tools, and how the plugin is put together. You do not need any of them to install and use Claude Bridge.

| Page | What it covers |
|---|---|
| [Tool reference](tools.md) | Every tool by name, with the permission it needs. It is made from the plugin's own code, so it always matches the version you have. |
| [Security in detail](security.md) | What a read, write and admin key can each see and do, the delete switch, the change record, and the safeguards on event webhooks. |
| [Letting your plugin add tools](providers.md) | For plugin authors: the one file, the hidden action and the startup line that let your plugin add tools of its own. |
| [How it is built](architecture.md) | The go-between script, the layout of the plugin's code, the search index and the tests. |
| [Upgrading to 3.0](upgrading-to-3.md) | For anyone who wrote down tool names before version 3.0: the old names and what replaced each one. |

The source code, and how to run the tests and add a tool, are on [GitHub](https://github.com/Highsteads/ClaudeBridge) — see [CONTRIBUTING](https://github.com/Highsteads/ClaudeBridge/blob/main/CONTRIBUTING.md).
