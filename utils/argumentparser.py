import argparse
import logging
import shlex

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, IO, Text, NoReturn


logger = logging.getLogger(__name__)


class ArgumentParserExit(Exception):
    pass


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super(ArgumentParser, self).__init__(*args, **kwargs)
        self._messages = []

    @staticmethod
    def convert_arg_line_to_args(arg_line: 'Text', start: int = 0):
        return shlex.split(arg_line)

    def _print_message(self, message: str, file: 'Optional[IO[str]]' = ...) -> None:
        # Bad workaround.
        # NOT THREADSAFE - multiple messages may use the same ArgParser at the same time
        self._messages.append(message)

    def consume_messages(self):
        # Bad workaround - part 2.
        messages = "".join(self._messages)
        self._messages = []
        return messages

    def exit(self, status: int = 0, message: 'Optional[Text]' = None) -> 'NoReturn':
        if message:
            self._print_message(message)
        raise ArgumentParserExit
