#! /usr/bin/python3
from __future__ import annotations
from dataclasses import dataclass
import re
import sys
from argparse import ArgumentParser
from typing import List, TextIO
from enum import Enum


class NegativeTimestampException(Exception):
    pass


@dataclass
class Timestamp:
    millis: int

    @classmethod
    def from_str(cls, timestamp_str: str) -> Timestamp:
        matches = re.fullmatch(
            r"^([01]?[0-9]|2[0-3]):([0-5]?[0-9]):([0-5]?[0-9]),([0-9]{1,3})$",
            timestamp_str,
        )
        if matches is None:
            raise ValueError(f"{timestamp_str} is not a valid timestamp")

        hours, minutes, seconds, millis = (
            int(matches[1]),
            int(matches[2]),
            int(matches[3]),
            int(matches[4]),
        )
        total_millis = (
            millis + 1000 * seconds + 60 * 1000 * minutes + 60 * 60 * 1000 * hours
        )
        return Timestamp(total_millis)

    def __str__(self) -> str:
        hours, rest = divmod(self.millis, 60 * 60 * 1000)
        minutes, rest = divmod(rest, 60 * 1000)
        seconds, millis = divmod(rest, 1000)

        return f"{str(hours).zfill(2)}:{str(minutes).zfill(2)}:{str(seconds).zfill(2)},{str(millis).zfill(3)}"

    def delayed_by(self, millis: int, clamp_to_zero: bool) -> Timestamp:
        """Note: parameter `millis` can take a negative value. The behavior if the resulting
        Timestamp is negative is dictated by `clamp_to_zero`."""
        if self.millis + millis < 0 and not clamp_to_zero:
            raise NegativeTimestampException()
        else:
            return Timestamp(max(self.millis + millis, 0))


@dataclass
class Subtitle:
    number: int
    start: Timestamp
    end: Timestamp
    text: List[str]

    def __str__(self) -> str:
        joined_text = "\n".join(self.text)
        return f"{self.number}\n{self.start} --> {self.end}\n{joined_text}\n"


class ParserState(Enum):
    NEW_SUBTITLE = 1
    TIMESTAMPS = 2
    TEXT = 3


def parse_srt_file(file: TextIO) -> List[Subtitle]:
    state = ParserState.NEW_SUBTITLE
    subtitles = []

    number = None
    start, end = None, None
    text = []

    for line in file:
        line = line.strip()
        if state == ParserState.NEW_SUBTITLE:
            if len(line) == 0:
                continue
            # .isdigit() may be too broad as it accepts Unicode fractions for example
            elif not line.isdigit():
                raise ValueError("expected a number, got", line)
            else:
                number = int(line)
                state = ParserState.TIMESTAMPS
        elif state == ParserState.TIMESTAMPS:
            timestamps = line.split("-->")
            if len(timestamps) != 2:
                raise ValueError("expected 2 timestamps separated by '-->', got", line)
            start = Timestamp.from_str(timestamps[0].strip())
            end = Timestamp.from_str(timestamps[1].strip())
            state = ParserState.TEXT
        elif state == ParserState.TEXT:
            # Empty line: finish building the current subtitle and reset.
            if len(line) == 0:
                if len(text) == 0:
                    raise ValueError(
                        "expected at least one line of text after timestamps"
                    )
                if number is None or start is None or end is None:
                    raise RuntimeError("invalid state")
                subtitles.append(Subtitle(number, start, end, text))
                number, start, end, text = None, None, None, []
                state = ParserState.NEW_SUBTITLE
            else:
                text.append(line)

    if state == ParserState.TIMESTAMPS:
        raise ValueError("file ended in the middle of incomplete subtitle")

    if state == ParserState.TEXT:
        if len(text) == 0:
            raise ValueError("file ended in the middle of incomplete subtitle")
        if number is None or start is None or end is None:
            raise RuntimeError("invalid state")
        subtitles.append(Subtitle(number, start, end, text))

    return subtitles


def delay_subtitles(subtitles: List[Subtitle], millis: int) -> List[Subtitle]:
    rv = []
    for sub in subtitles:
        try:
            start, end = (
                sub.start.delayed_by(millis, clamp_to_zero=True),
                sub.end.delayed_by(millis, clamp_to_zero=False),
            )
            rv.append(Subtitle(len(rv) + 1, start, end, sub.text.copy()))
        except NegativeTimestampException:
            print(
                f"End of subtitle {sub.number} was advanced before 00:00:00,000 so the whole \
subtitle was removed."
            )
    return rv


def write_srt_file(filename: str, subtitles: List[Subtitle]):
    with open(filename, "w") as f:
        for sub in subtitles:
            f.write(str(sub))
            if not sub is subtitles[-1]:
                f.write("\n")


if __name__ == "__main__":
    main_parser = ArgumentParser(
        description="SRTtools: modify SRT subtitle files easily."
    )
    main_parser.add_argument("filename", help="File to modify.")
    subparsers = main_parser.add_subparsers(
        title="subcommands", dest="subcommand", required=True
    )

    delay_parser = subparsers.add_parser(
        "delay",
        help="Delays all the subtitles of the file by\
                                         the number of milliseconds passed as argument.\
                                         Creates a new file prefixed with 'delayed_'.",
    )
    delay_parser.add_argument(
        "milliseconds",
        type=int,
        help="Can be a negative value, in which case if subtitles are advanced before 0 seconds\
            (timestamp 00:00:00,000) they will be removed from the file.",
    )

    args = main_parser.parse_args(args=None if sys.argv[1:] else ["--help"])

    with open(args.filename) as f:
        original_subtitles = parse_srt_file(f)

    if args.subcommand == "delay":
        modified_subtitles = delay_subtitles(original_subtitles, args.milliseconds)
        write_srt_file("delayed_" + args.filename, modified_subtitles)
