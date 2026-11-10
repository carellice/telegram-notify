---
name: telegram
description: Send Claude Code recaps, links and attachments to the user's Telegram. Use for /telegram, "send me this on Telegram", "mandamelo su Telegram", to turn automatic Telegram recaps on/off for this session or globally, or to send recaps to a Telegram group or channel. Subcommands - help, setup, on, on global, off, off global, status, test, link, or no argument to send a recap now.
argument-hint: "[help | setup | on [global] | off [global] | status | test | link [session [reset]] | <note>]"
---

# telegram-notify

Script: `"${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"` (POSIX sh wrapper that finds Python 3).
Run it from the Bash tool as `sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" <command> ...`.
The UserPromptSubmit hook adds `telegram-notify: current session_id=<id>` to context on every
`/telegram` prompt. Use that id wherever `<SID>` appears below.

Arguments: `$ARGUMENTS`

## 1. Check configuration first

Run `status --session <SID>`. If `"configured": false` and the argument is not `setup`,
tell the user setup is needed and continue with **setup**.

## 2. Act on the argument

- **setup**: the bot token is a secret. Never ask the user to paste it in chat and never type it
  yourself. The user runs the interactive setup in their own terminal:
  `sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" setup`
  If a tool exists that opens a command in the user's own terminal tab, use it to start that
  command; otherwise give the user the command in a code block. Explain the 3 steps it guides:
  create a bot with @BotFather and paste its token, send any message to the bot, wait for the
  test message. When the user says it is done, run `status` to confirm.
- **on** / **off**: `on --session <SID>` or `off --session <SID>`. Session setting overrides global,
  so `off` in a session mutes it even when global mode is on.
- **on global** / **off global**: `on --global` / `off --global`. Global mode means every
  Claude Code session on this computer sends a recap after each prompt.
- **status**: run `status --session <SID>` and report in one or two lines.
- **test**: run `test --session <SID>`.
- **help** (or "comandi", "commands", "?"): run `help` and show its list to the user,
  translated into the user's language, keeping the same groups and order. Use one Markdown
  table per group (command | what it does). Commands stay verbatim. Add nothing else.
- **link** / **channel** / **group**: choose where recaps go. There is one default chat and
  an optional chat per session that overrides it.
  - `link --session <SID>` lists the default, this session's chat and the known chats
    (id, type, name). If more than one fits, ask the user which.
  - `link --chat <id>` sets the **default** chat for every session.
  - `link session` (or "only this session", "solo questa sessione"): `link --chat <id> --session <SID>`.
  - `link session reset`: `link --session <SID> --reset`, back to the default.
  Each link sends a test message to the chat first. If no chat is listed, `link` waits up to
  3 minutes: tell the user to add the bot to the group or channel (in a channel as admin with
  "Post messages") and post a message there. `@channelusername` also works as id.
- **no argument, or a note**: send a recap now (see section 3) of the work done so far in this
  conversation. A note after `/telegram` says what to focus on or what to attach.

After `on`/`off`, confirm in one line. Do not send a recap for the `/telegram` turn itself.

## 3. Writing and sending a recap

- User's language. Plain text. One message per project worked on: send the command once
  per project. Format of each message:

  ```
  <Project name>
  - <thing done>
  - <thing done>
  - Da fare: <pending item, only if any>
  <GitHub link (commit, PR, release), only if any>
  ```

  Short list items, no prose. Links in full. Work not tied to a project: one message
  with a fitting title.
- Attach files the user would want on the phone: screenshots, generated images, reports,
  built packages. Max 50 MB each. Skip source files unless asked.
- Never include secrets, tokens, passwords or `.env` contents.
- Send:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" send --session <SID> --file "path/one.png" <<'EOF'
<recap text>
EOF
```

`--file` repeats for each attachment. Without the Bash tool, pass the text with `--text "..."`.
`--html` enables Telegram HTML formatting (`<b>`, `<i>`, `<a href>`, `<code>`).
If the command prints an error, tell the user in one line.
