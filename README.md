<p align="center">
  <img src="assets/icon.png" alt="telegram-notify icon" width="180">
</p>

<h1 align="center">telegram-notify</h1>

<p align="center">
  Claude Code recaps, links and attachments, straight to your Telegram.
</p>

A Claude Code plugin that sends recaps of Claude's work to your Telegram, with links and
attachments. Use it on demand, or turn it on so a recap arrives after every prompt.

## Requirements

- Claude Code with plugin support
- Python 3.8+ (`python3`, `python` or `py` on PATH). No packages to install.
- A POSIX `sh` (macOS/Linux built in; Git Bash on Windows, which Claude Code already uses)

## Install

```bash
claude plugin marketplace add carellice/telegram-notify
claude plugin install telegram-notify@telegram-notify
```

For local development, point Claude Code at a clone instead:

```bash
claude --plugin-dir /path/to/telegram-notify
```

## First-time setup

Run `/telegram setup` in Claude Code. It starts a short guided setup in your terminal:

1. In Telegram, open @BotFather, send `/newbot`, and copy the token.
2. Paste the token into the setup prompt (input hidden; it never goes through the chat).
3. Send any message to your new bot. Setup detects your chat and sends a test message.

You can also run it yourself: `sh scripts/run.sh setup`.

Config lives in `~/.claude/telegram-notify/config.json`. The environment variables
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` override it.

## Commands

| Command | Effect |
| --- | --- |
| `/telegram` | Send a recap of the work so far now |
| `/telegram <note>` | Recap now, focused on the note (e.g. "attach the screenshot") |
| `/telegram on` / `off` | Recap after every prompt in this session |
| `/telegram on global` / `off global` | Recap after every prompt in every session |
| `/telegram status` | Show configuration and mode |
| `/telegram test` | Send a test message |
| `/telegram link` | Set the default chat (private chat, group or channel) |
| `/telegram link session` | Use another chat for this session only |
| `/telegram link session reset` | This session goes back to the default chat |

### Groups, channels and per-session chats

Add the bot to the group or channel. In a channel it must be an admin with "Post messages".
Post any message there, then run `/telegram link` and pick the chat.

Recaps go to the default chat. `/telegram link session` points one session at a different
chat without touching the default, so a session can report to a team channel while the
others keep using your private chat. Chats you linked once stay listed, so switching back
needs no new message.

A session setting wins over the global one: `/telegram off` mutes one session while global
mode stays on for the others.

## How it works

- A `UserPromptSubmit` hook checks whether recaps are on. If so, it tells Claude to finish
  the prompt with a short Telegram recap, sent through `scripts/tg.py`.
- A `Stop` hook checks that the recap went out. If not, it asks Claude once to send it.
- `scripts/tg.py` talks to the Telegram Bot API with the Python standard library only.

## Limits

- Telegram caps messages at 4096 characters (longer text is split) and bot uploads at 50 MB.
- Anyone with your bot token can post as your bot. Keep the config file private.

## License

MIT
