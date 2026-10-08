#!/usr/bin/env python3
"""Send one JSON QMP command through a private Unix socket; report its real reply."""
import argparse
import json
import socket
import sys
import time


def key_codes(text):
    punctuation = {" ": ["spc"], ".": ["dot"], "/": ["slash"], "-": ["minus"],
                   "_": ["shift", "minus"], ":": ["shift", "semicolon"], ";": ["semicolon"],
                   "|": ["shift", "backslash"], ">": ["shift", "dot"],
                   "'": ["apostrophe"], '"': ["shift", "apostrophe"],
                   "$": ["shift", "4"], "=": ["equal"], "\\": ["backslash"],
                   "?": ["shift", "slash"], "&": ["shift", "7"], "*": ["shift", "8"],
                   "[": ["bracket_left"], "]": ["bracket_right"], ",": ["comma"],
                   "{": ["shift", "bracket_left"], "}": ["shift", "bracket_right"],
                   "@": ["shift", "2"]}
    codes = []
    for char in text:
        if char.isascii() and char.isalnum():
            codes.append((["shift"] if char.isupper() else []) + [char.lower()])
        elif char in punctuation:
            codes.append(punctuation[char])
        else:
            raise ValueError(f"unsupported character: {char!r}")
    return codes


def reply(stream, deadline=None):
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("QMP reply timed out")
        line = stream.readline()
        if not line:
            raise ConnectionError("QEMU closed the monitor connection")
        value = json.loads(line)
        if "error" in value:
            raise RuntimeError(value["error"])
        if "return" in value:
            return value["return"]


def execute(path, command):
    deadline = time.monotonic() + 10
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(10)
        client.connect(path)
        with client.makefile("rwb") as stream:
            greeting = json.loads(stream.readline())
            if "QMP" not in greeting:
                raise ValueError("not a QMP monitor")
            for request in [{"execute": "qmp_capabilities"}, command]:
                client.settimeout(max(0.01, deadline - time.monotonic()))
                stream.write(json.dumps(request).encode() + b"\n")
                stream.flush()
                result = reply(stream, deadline)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("socket")
    parser.add_argument("command", nargs="?", help="JSON object, e.g. '{\"execute\":\"query-kvm\"}'")
    parser.add_argument("--text", help="type ASCII text into the visibly focused guest console")
    parser.add_argument("--text-stdin", action="store_true", help="read one text line from stdin, keeping test credentials out of argv")
    parser.add_argument("--enter", action="store_true")
    args = parser.parse_args()
    if args.text_stdin:
        if args.text is not None:
            parser.error("choose --text or --text-stdin")
        args.text = sys.stdin.readline().rstrip("\r\n")
    if (args.command is None) == (args.text is None) or (args.enter and args.text is None):
        parser.error("choose one JSON command or --text; --enter requires --text")
    if args.text is not None:
        codes = key_codes(args.text) + ([["ret"]] if args.enter else [])
        for keys in codes:
            execute(args.socket, {"execute": "send-key", "arguments": {
                "keys": [{"type": "qcode", "data": key} for key in keys], "hold-time": 30}})
            time.sleep(0.05)
        print(f"Sent {len(codes)} key sequences; inspect the guest result.")
    else:
        print(json.dumps(execute(args.socket, json.loads(args.command)), indent=2))
