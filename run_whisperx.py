#!/usr/bin/env python3
import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


COMMAND_FILE = Path(__file__).with_name("whisper-cmd.txt")
SKIP_VALUE_FLAGS = {"--output_format", "--output_dir"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run WhisperX using the baseline options from whisper-cmd.txt."
    )
    parser.add_argument("audio_file", help="Path to the audio file to transcribe.")
    parser.add_argument(
        "--output-dir",
        help="Directory for generated transcript files. Defaults to <audio dir>/transcripts.",
    )
    parser.add_argument(
        "--type",
        choices=["all", "json", "srt", "both"],
        default="all",
        help="Transcript output type to generate.",
    )
    return parser.parse_args()


def load_base_command():
    if not COMMAND_FILE.exists():
        raise FileNotFoundError(f"Missing command file: {COMMAND_FILE}")

    logical_lines = []

    for raw_line in COMMAND_FILE.read_text().splitlines():
        line = raw_line.strip()

        if not line:
            continue

        logical_lines.append(line[:-1].rstrip() if line.endswith("\\") else line)

    tokens = shlex.split(" ".join(logical_lines))

    if not tokens or tokens[0] != "whisperx":
        raise ValueError("whisper-cmd.txt must start with a whisperx command.")

    return tokens


def resolve_output_dir(audio_path, output_dir_arg):
    if output_dir_arg:
        return Path(output_dir_arg).expanduser().resolve()

    return (audio_path.parent / "transcripts").resolve()


def build_command(audio_path, output_dir, output_type):
    tokens = load_base_command()
    command = [tokens[0]]
    input_replaced = False
    i = 1

    while i < len(tokens):
        token = tokens[i]

        if token in SKIP_VALUE_FLAGS:
            i += 2
            continue

        if token == "--hf_token":
            if i + 1 >= len(tokens):
                raise ValueError("whisper-cmd.txt has --hf_token without a value.")

            # Prefer an existing Hugging Face CLI login instead of echoing tokens in commands.
            i += 2
            continue

        if not input_replaced and not token.startswith("-"):
            command.append(str(audio_path))
            input_replaced = True
            i += 1
            continue

        command.append(os.path.expandvars(token))
        i += 1

    if not input_replaced:
        command.append(str(audio_path))

    command.extend(["--output_format", output_type])
    command.extend(["--output_dir", str(output_dir)])
    return command


def output_formats(output_type):
    if output_type == "both":
        return ["json", "srt"]
    return [output_type]


def main():
    args = parse_args()

    if shutil.which("whisperx") is None:
        print("Error: whisperx is not installed or not on PATH.", file=sys.stderr)
        return 127

    audio_path = Path(args.audio_file).expanduser().resolve()

    if not audio_path.exists():
        print(f"Error: audio file not found: {audio_path}", file=sys.stderr)
        return 1

    output_dir = resolve_output_dir(audio_path, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        commands = [build_command(audio_path, output_dir, output_type) for output_type in output_formats(args.type)]
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    for command in commands:
        print("Running:")
        print(" ".join(shlex.quote(part) for part in command), flush=True)
        result = subprocess.run(command)
        if result.returncode != 0:
            return result.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
