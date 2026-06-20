from __future__ import annotations

import argparse
import json
import sys

import httpx

from tempa.main import main as run_daemon


def _daemon_url() -> str:
    from tempa.settings import get_settings

    return f"http://127.0.0.1:{get_settings().tempa_daemon_port}"


def cmd_setup() -> None:
    from tempa.meet.consent import grant_recording_consent
    from tempa.settings import get_settings

    settings = get_settings()
    settings.ensure_dirs()
    print("Tempa setup")
    print(f"  Data dir: {settings.tempa_data_dir}")
    print(f"  Daemon:   {_daemon_url()}")
    print(f"  Dashboard: {_daemon_url()}/")
    print()
    print("1. Set GROQ_API_KEY in .env or run: tempa setup --groq-key YOUR_KEY")
    print("2. Connect Google: open dashboard Connections → Google")
    print("3. WhatsApp QR: tempa whatsapp-qr  (or extension popup)")
    print("4. Meet auth: tempa meet-auth")
    consent = input("Grant meeting recording consent now? [y/N] ").strip().lower()
    if consent == "y":
        grant_recording_consent()
        print("Recording consent granted.")


def cmd_chat() -> None:
    print("Tempa chat (Ctrl+C to exit)")
    while True:
        try:
            message = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue
        try:
            with httpx.Client(timeout=120) as client:
                res = client.post(f"{_daemon_url()}/api/chat", json={"message": message})
                # SSE stream — read last data line
                content = ""
                for line in res.text.splitlines():
                    if line.startswith("data:"):
                        try:
                            payload = json.loads(line[5:].strip())
                            if payload.get("content"):
                                content = payload["content"]
                        except json.JSONDecodeError:
                            pass
                print(f"Tempa> {content or res.text}")
        except httpx.ConnectError:
            print("Daemon offline. Start with: tempa start")
            break
        except Exception as exc:
            print(f"Error: {exc}")


def cmd_whatsapp_qr() -> None:
    try:
        with httpx.Client(timeout=30) as client:
            res = client.get(f"{_daemon_url()}/api/connections/whatsapp")
            res.raise_for_status()
            data = res.json()
    except httpx.ConnectError:
        print("Daemon offline. Start with: tempa start", file=sys.stderr)
        sys.exit(1)
    qr = data.get("qr_code")
    state = data.get("connection_state", data.get("status"))
    print(f"Connection: {json.dumps(state)}")
    if qr:
        if qr.startswith("data:image"):
            import base64
            import tempfile
            from pathlib import Path

            b64 = qr.split(",", 1)[-1]
            out = Path(tempfile.gettempdir()) / "tempa-whatsapp-qr.png"
            out.write_bytes(base64.b64decode(b64))
            print(f"QR saved to: {out}")
        else:
            print(f"QR base64 length: {len(qr)}")
    else:
        print("No QR available (may already be connected).")


def main() -> None:
    parser = argparse.ArgumentParser(prog="tempa")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start", help="Start Tempa daemon")
    setup = sub.add_parser("setup", help="Interactive setup wizard")
    setup.add_argument("--groq-key", default=None)
    sub.add_parser("chat", help="CLI chat with coordinator")
    sub.add_parser("whatsapp-qr", help="Fetch and save WhatsApp QR")
    auth = sub.add_parser("meet-auth", help="Generate Google storage state for Meet bot")
    auth.add_argument("--output", default=None)

    args = parser.parse_args()
    if args.command == "setup":
        if getattr(args, "groq_key", None):
            from tempa.settings import get_settings

            settings = get_settings()
            path = settings.groq_key_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args.groq_key.strip(), encoding="utf-8")
            print(f"Groq key saved to {path}")
        cmd_setup()
    elif args.command == "chat":
        cmd_chat()
    elif args.command == "whatsapp-qr":
        cmd_whatsapp_qr()
    elif args.command == "start" or args.command is None:
        run_daemon()
    elif args.command == "meet-auth":
        from tempa.settings import get_settings

        settings = get_settings()
        output = args.output or str(settings.google_storage_state_path)
        from tempa.meet.auth_generate import main as auth_main

        sys.argv = ["meeto-auth", "--output", output]
        auth_main()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
