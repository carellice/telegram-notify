#!/usr/bin/env python3
"""telegram-notify: send Claude Code recaps to Telegram.

Standard library only. Commands:
  setup [--token T]            interactive first-time configuration
  status [--session S]         show configuration and mode
  on|off [--session S|--global] enable/disable recaps
  send --session S [--file P ...] [--html] [--text T]   (text also from stdin)
  test [--session S]           send a test message
  help                         list the /telegram commands
  link [--chat ID] [--session S] [--reset]
                               set the default chat, or this session's chat
  hook-prompt | hook-stop      used by the plugin hooks (JSON on stdin)
"""

import argparse
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 4096
MAX_FILE = 50 * 1024 * 1024
MAX_PHOTO = 10 * 1024 * 1024
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
CMD_RE = re.compile(r"^\s*/(?:telegram-notify:)?telegram(?:\s|$)", re.I)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ---------- paths and state ----------

def home_dir():
    base = os.environ.get("TELEGRAM_NOTIFY_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".claude", "telegram-notify")
    os.makedirs(os.path.join(base, "sessions"), exist_ok=True)
    return base


def config_path():
    return os.path.join(home_dir(), "config.json")


def global_flag():
    return os.path.join(home_dir(), "global_on")


def session_path(sid):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", sid)
    return os.path.join(home_dir(), "sessions", safe + ".json")


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_config(sid=None):
    """Token and target chat: the session's own chat if set, else the default."""
    cfg = read_json(config_path(), {})
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("token")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or cfg.get("chat_id")
    if sid and load_session(sid).get("chat_id"):
        chat_id = load_session(sid)["chat_id"]
    if token and chat_id:
        return {"token": token, "chat_id": str(chat_id)}
    return None


def known_chats():
    return read_json(config_path(), {}).get("chats", {})


def chat_label(chat_id):
    c = known_chats().get(str(chat_id))
    return "{} ({})".format(c["name"], chat_id) if c else str(chat_id)


def load_session(sid):
    return read_json(session_path(sid), {}) if sid else {}


def save_session(sid, data):
    if sid:
        write_json(session_path(sid), data)


def is_enabled(sid):
    mode = load_session(sid).get("mode")  # "on", "off" or None
    if mode == "on":
        return True
    if mode == "off":
        return False
    return os.path.exists(global_flag())


def script_cmd():
    """Command line that re-runs this script with the same interpreter."""
    exe = sys.executable.replace("\\", "/")
    me = os.path.abspath(__file__).replace("\\", "/")
    return '"{}" "{}"'.format(exe, me)


# ---------- Telegram API ----------

def api_call(token, method, fields=None, files=None, timeout=60):
    url = API.format(token=token, method=method)
    if files:
        boundary = uuid.uuid4().hex
        body = bytearray()
        for k, v in (fields or {}).items():
            body += "--{}\r\nContent-Disposition: form-data; name=\"{}\"\r\n\r\n{}\r\n".format(
                boundary, k, v).encode("utf-8")
        for k, path in files.items():
            name = os.path.basename(path)
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            with open(path, "rb") as f:
                data = f.read()
            body += ("--{}\r\nContent-Disposition: form-data; name=\"{}\"; filename=\"{}\"\r\n"
                     "Content-Type: {}\r\n\r\n").format(boundary, k, name, ctype).encode("utf-8")
            body += data + b"\r\n"
        body += "--{}--\r\n".format(boundary).encode("utf-8")
        req = urllib.request.Request(url, data=bytes(body))
        req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    else:
        data = urllib.parse.urlencode(fields or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            res = json.loads(e.read().decode("utf-8"))
        except Exception:
            res = {"ok": False, "description": "HTTP {}".format(e.code)}
    if not res.get("ok"):
        raise RuntimeError(res.get("description", "Telegram API error"))
    return res.get("result")


def split_text(text):
    chunks = []
    while len(text) > MAX_TEXT:
        cut = text.rfind("\n", 0, MAX_TEXT)
        if cut < MAX_TEXT // 2:
            cut = MAX_TEXT
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text.strip():
        chunks.append(text)
    return chunks


def send_text(cfg, text, html=False):
    for chunk in split_text(text):
        fields = {"chat_id": cfg["chat_id"], "text": chunk}
        if html:
            fields["parse_mode"] = "HTML"
        try:
            api_call(cfg["token"], "sendMessage", fields)
        except RuntimeError as e:
            if html and "parse" in str(e).lower():
                # malformed HTML: resend as plain text
                api_call(cfg["token"], "sendMessage", {"chat_id": cfg["chat_id"], "text": chunk})
            else:
                raise


def send_file(cfg, path):
    size = os.path.getsize(path)
    if size > MAX_FILE:
        raise RuntimeError("{} exceeds 50 MB Telegram bot limit".format(path))
    ext = os.path.splitext(path)[1].lower()
    if ext in PHOTO_EXT and size <= MAX_PHOTO:
        try:
            api_call(cfg["token"], "sendPhoto", {"chat_id": cfg["chat_id"]}, {"photo": path}, 300)
            return
        except RuntimeError:
            pass  # e.g. bad dimensions: fall back to document
    api_call(cfg["token"], "sendDocument", {"chat_id": cfg["chat_id"]}, {"document": path}, 300)


# ---------- commands ----------

def ask(prompt, secret=False):
    if secret:
        try:
            import getpass
            return getpass.getpass(prompt).strip()
        except Exception:
            pass
    return input(prompt).strip()


def cmd_setup(args):
    print("== telegram-notify setup ==")
    print("1. Open Telegram, talk to @BotFather, send /newbot and follow the steps.")
    print("2. Copy the token BotFather gives you (looks like 123456:ABC-DEF...).")
    token = args.token or ask("Paste bot token (input hidden): ", secret=True)
    if not token:
        print("No token given. Aborted.")
        return 1
    try:
        me = api_call(token, "getMe")
    except Exception as e:
        print("Token rejected by Telegram: {}".format(e))
        return 1
    bot = me.get("username", "?")
    print("Bot found: @{}".format(bot))

    # drop old updates so we only catch a fresh message
    offset = 0
    try:
        old = api_call(token, "getUpdates", {"timeout": 0})
        if old:
            offset = old[-1]["update_id"] + 1
    except Exception:
        pass

    print("3. Open https://t.me/{} and send it any message (e.g. /start).".format(bot))
    print("   For a group or channel: add the bot there and post a message.")
    print("   Waiting up to 3 minutes...")
    chat = wait_for_chat(token, offset)
    if not chat:
        print("No message received. Run setup again.")
        return 1
    save_chat(token, chat)
    print("Setup complete.")
    return 0


def update_chat(u):
    """Chat from a private message, group/channel post or the bot being added to a chat."""
    for key in ("message", "channel_post", "my_chat_member"):
        if u.get(key) and u[key].get("chat"):
            return u[key]["chat"]
    return None


def chat_name(chat):
    return chat.get("title") or " ".join(
        x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username", "")


def wait_for_chat(token, offset, seconds=180):
    allowed = '["message","channel_post","my_chat_member"]'
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            ups = api_call(token, "getUpdates", {"timeout": 25, "offset": offset,
                                                 "allowed_updates": allowed}, timeout=40)
        except Exception as e:
            print("getUpdates error: {}".format(e))
            time.sleep(3)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            chat = update_chat(u)
            if chat:
                # confirm offset so the update is not returned again
                try:
                    api_call(token, "getUpdates", {"timeout": 0, "offset": offset})
                except Exception:
                    pass
                return chat
    return None


def save_chat(token, chat, sid=None):
    """Test-send to chat, then make it the default (or this session's chat when sid is given)."""
    chat_id = str(chat["id"])
    where = "this session" if sid else "default"
    send_text({"token": token, "chat_id": chat_id},
              "telegram-notify linked ({}). Claude Code recaps will arrive here.".format(where))
    cfg = read_json(config_path(), {})
    cfg["token"] = token
    if sid:
        st = load_session(sid)
        st["chat_id"] = chat_id
        save_session(sid, st)
    else:
        cfg["chat_id"] = chat_id
    # remember names so `link` can list chats after Telegram drops old updates
    cfg.setdefault("chats", {})[chat_id] = {"name": chat_name(chat), "type": chat.get("type", "?")}
    write_json(config_path(), cfg)
    try:
        os.chmod(config_path(), 0o600)
    except Exception:
        pass
    print("Chat linked as {}: {} ({}, {})".format(
        where, chat_name(chat), chat.get("type", "?"), chat_id))
    print("Test message sent.")


def cmd_link(args):
    """Point recaps at another chat (private, group or channel) without re-entering the token."""
    cfg = load_config()
    if not cfg:
        print("Not configured. Run setup first.")
        return 1
    token = cfg["token"]
    if args.reset:
        if not args.session:
            print("--reset needs --session ID")
            return 1
        st = load_session(args.session)
        st.pop("chat_id", None)
        save_session(args.session, st)
        print("Session chat cleared. Recaps go to the default: {}".format(chat_label(cfg["chat_id"])))
        return 0
    if args.chat:
        chat = api_call(token, "getChat", {"chat_id": args.chat})
        save_chat(token, chat, args.session)
        return 0
    # list chats linked before plus chats the bot has seen recently
    chats = {cid: dict(c, id=cid) for cid, c in known_chats().items()}
    try:
        for u in api_call(token, "getUpdates", {"timeout": 0, "allowed_updates":
                                                '["message","channel_post","my_chat_member"]'}):
            chat = update_chat(u)
            if chat:
                chats[str(chat["id"])] = {"id": str(chat["id"]), "name": chat_name(chat),
                                          "type": chat.get("type", "?")}
    except Exception as e:
        print("getUpdates error: {}".format(e))
    print("Default chat: {}".format(chat_label(cfg["chat_id"])))
    if args.session:
        sc = load_session(args.session).get("chat_id")
        print("This session: {}".format(chat_label(sc) if sc else "uses the default"))
    if chats:
        print("Known chats:")
        for c in chats.values():
            print("  {}  {}  {}".format(c["id"], c.get("type", "?"), c.get("name", "")))
        print("Link one with: link --chat <id> [--session ID]")
        return 0
    print("No chats seen yet. Add the bot to the group/channel and post a message there.")
    print("Waiting up to 3 minutes...")
    chat = wait_for_chat(token, 0)
    if not chat:
        print("No message received.")
        return 1
    save_chat(token, chat, args.session)
    return 0


def cmd_status(args):
    cfg = load_config()
    out = {
        "configured": bool(cfg),
        "config_path": config_path(),
        "global": os.path.exists(global_flag()),
    }
    if cfg:
        out["default_chat"] = chat_label(cfg["chat_id"])
        out["token"] = cfg["token"][:6] + "..." + cfg["token"][-4:]
    if args.session:
        st = load_session(args.session)
        out["session_mode"] = st.get("mode") or "default"
        out["enabled_here"] = is_enabled(args.session)
        out["session_chat"] = chat_label(st["chat_id"]) if st.get("chat_id") else "default"
    print(json.dumps(out, indent=2))
    return 0


def cmd_toggle(args, on):
    if args.global_:
        if on:
            open(global_flag(), "w").close()
        elif os.path.exists(global_flag()):
            os.remove(global_flag())
        print("Global recaps: {}".format("ON" if on else "OFF"))
    elif args.session:
        st = load_session(args.session)
        st["mode"] = "on" if on else "off"
        save_session(args.session, st)
        print("Session recaps: {}".format("ON" if on else "OFF"))
    else:
        print("Need --session ID or --global")
        return 1
    if on and not load_config():
        print("Warning: not configured yet. Run setup first.")
    return 0


def cmd_send(args):
    cfg = load_config(args.session)
    if not cfg:
        print("Not configured. Run setup first.")
        return 1
    text = args.text
    if text is None and not sys.stdin.isatty():
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    text = (text or "").strip()
    errors = []
    if text:
        send_text(cfg, text, args.html)
    for p in args.file or []:
        try:
            send_file(cfg, p)
        except Exception as e:
            errors.append("{}: {}".format(p, e))
    if not text and not args.file:
        print("Nothing to send.")
        return 1
    if args.session:
        st = load_session(args.session)
        st["sent_at"] = time.time()
        save_session(args.session, st)
    for e in errors:
        print("Attachment failed: " + e)
    print("Sent." if not errors else "Sent with errors.")
    return 1 if errors else 0


COMMANDS = [
    ("Setup", [
        ("/telegram setup", "First-time setup: link your bot and chat"),
        ("/telegram status", "Show configuration, mode and target chat"),
        ("/telegram test", "Send a test message"),
    ]),
    ("Send", [
        ("/telegram", "Send a recap of the work so far now"),
        ("/telegram <note>", "Recap now, focused on the note (e.g. attach the screenshot)"),
    ]),
    ("Automatic recaps", [
        ("/telegram on", "Recap after every prompt in this session"),
        ("/telegram off", "Stop recaps in this session (even when global is on)"),
        ("/telegram on global", "Recap after every prompt in every session"),
        ("/telegram off global", "Turn global recaps off"),
    ]),
    ("Chats", [
        ("/telegram link", "List chats and set the default one"),
        ("/telegram link session", "Use another chat for this session only"),
        ("/telegram link session reset", "This session goes back to the default chat"),
    ]),
    ("Help", [
        ("/telegram help", "Show this list"),
    ]),
]


def cmd_help(args):
    width = max(len(c) for _, cmds in COMMANDS for c, _ in cmds)
    for i, (group, cmds) in enumerate(COMMANDS):
        if i:
            print()
        print(group)
        for c, desc in cmds:
            print("  {}  {}".format(c.ljust(width), desc))
    return 0


def cmd_test(args):
    cfg = load_config(args.session)
    if not cfg:
        print("Not configured. Run setup first.")
        return 1
    send_text(cfg, "telegram-notify test message.")
    print("Sent to {}.".format(chat_label(cfg["chat_id"])))
    return 0


def read_hook_input():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except Exception:
        return {}


def emit_context(text):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": text}}))


def cmd_hook_prompt(args):
    data = read_hook_input()
    sid = data.get("session_id") or ""
    prompt = data.get("prompt") or ""
    if not sid:
        return 0
    st = load_session(sid)
    if CMD_RE.match(prompt):
        # a /telegram command turn never needs a recap of itself
        st["turn_start"] = time.time()
        st["exempt"] = True
        save_session(sid, st)
        emit_context("telegram-notify: current session_id={}; script command: {}".format(
            sid, script_cmd()))
        return 0
    if not is_enabled(sid):
        return 0
    st["turn_start"] = time.time()
    st["exempt"] = False
    save_session(sid, st)
    if not load_config():
        emit_context("telegram-notify recaps are ON but the plugin is not configured; "
                     "the user can run /telegram setup.")
        return 0
    emit_context(
        "telegram-notify recaps are ON for this session (session_id={sid}). The user wants, "
        "after the work for this prompt is finished, a short Telegram recap in the user's "
        "language: what was done, results, anything pending, with useful links. Files "
        "worth having on the phone (images, reports, builds) go as attachments. Send it as "
        "the last step with:\n"
        "{cmd} send --session {sid} [--file PATH ...] <<'EOF'\n<recap text>\nEOF\n"
        "Plain text, max ~15 lines; never include secrets. If the user asks not to send a "
        "recap for this prompt, none is sent.".format(sid=sid, cmd=script_cmd()))
    return 0


def cmd_hook_stop(args):
    data = read_hook_input()
    sid = data.get("session_id") or ""
    if not sid or data.get("stop_hook_active"):
        return 0
    if not is_enabled(sid) or not load_config():
        return 0
    st = load_session(sid)
    start = st.get("turn_start")
    if not start or st.get("exempt"):
        return 0
    if st.get("sent_at", 0) >= start or st.get("reminded_at", 0) >= start:
        return 0
    st["reminded_at"] = time.time()
    save_session(sid, st)
    print(json.dumps({
        "decision": "block",
        "reason": "telegram-notify: the Telegram recap for this prompt has not been sent yet. "
                  "Send it now with: {} send --session {} <<'EOF' ... EOF. "
                  "If the user asked not to send a recap for this prompt, stop without "
                  "sending.".format(script_cmd(), sid),
    }))
    return 0


def main():
    p = argparse.ArgumentParser(prog="tg.py")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("setup")
    s.add_argument("--token")
    s = sub.add_parser("status")
    s.add_argument("--session")
    for name in ("on", "off"):
        s = sub.add_parser(name)
        s.add_argument("--session")
        s.add_argument("--global", dest="global_", action="store_true")
    s = sub.add_parser("send")
    s.add_argument("--session")
    s.add_argument("--file", action="append")
    s.add_argument("--text")
    s.add_argument("--html", action="store_true")
    s = sub.add_parser("test")
    s.add_argument("--session")
    sub.add_parser("help")
    s = sub.add_parser("link")
    s.add_argument("--chat")
    s.add_argument("--session")
    s.add_argument("--reset", action="store_true")
    sub.add_parser("hook-prompt")
    sub.add_parser("hook-stop")
    args = p.parse_args()

    if args.cmd in ("hook-prompt", "hook-stop"):
        # hooks must never break the session
        try:
            return cmd_hook_prompt(args) if args.cmd == "hook-prompt" else cmd_hook_stop(args)
        except Exception as e:
            print("telegram-notify hook error: {}".format(e), file=sys.stderr)
            return 0
    handlers = {
        "setup": cmd_setup, "status": cmd_status, "send": cmd_send, "test": cmd_test,
        "link": cmd_link, "help": cmd_help,
        "on": lambda a: cmd_toggle(a, True), "off": lambda a: cmd_toggle(a, False),
    }
    if args.cmd not in handlers:
        p.print_help()
        return 1
    try:
        return handlers[args.cmd](args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print("Error: {}".format(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
