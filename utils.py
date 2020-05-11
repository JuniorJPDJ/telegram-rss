import argparse
import shlex

import durations_nlp
from telethon.tl.types import MessageEntityBotCommand
import telethon
import yaml

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, IO, Text, NoReturn, Union, Callable, ClassVar, Generator, List
    from telethon import events, types


class TelegramClient(telethon.TelegramClient):
    # A bit better than before, but still workaround
    # Still waiting for this issue to resolve this problem:
    # https://github.com/LonamiWebs/Telethon/issues/1344
    def __init__(self, *args, **kwargs):
        super(TelegramClient, self).__init__(*args, **kwargs)
        self.me = None

    async def get_me(self, input_peer: bool = False) -> 'Union[types.User, types.InputPeerUser]':
        me = await super(TelegramClient, self).get_me(input_peer)
        if not input_peer:
            self.me = me
        return me

    async def _start(self, *args, **kwargs):
        ret = await super(TelegramClient, self)._start(*args, **kwargs)
        await self.get_me()
        return ret


class Namespace(dict):
    def __getattr__(self, *args, **kwargs):
        return self.__getitem__(*args, **kwargs)


class ArgParserExit(Exception):
    pass


class ArgParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super(ArgParser, self).__init__(*args, **kwargs)
        self._messages = []

    @staticmethod
    def convert_arg_line_to_args(arg_line: 'Text'):
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
        raise ArgParserExit


def command(cmd: str, argparser: 'Optional[ArgParser]' = None):
    # TODO: User/Group/Channel tagging as an argument
    """
    Parses command `cmd` from Telegram message using `argparser`

    Pass this function as `func` argument for NewMessage event in event handler decorator
    It will handle commands in format `/cmd` and `/cmd@bot_username` and set `event.cmd` to corresponding `MessageEntityBotCommand`
    It will NOT handle commands inside messages, just in start of message!

    :param cmd:            command phrase/name
    :param argparser:     ArgParser with registered command arguments
    :return:            function to be handled by func argument of NewMessage events
    """
    if argparser is None:
        argparser = ArgParser()
    cmd = cmd if cmd.startswith("/") else "/" + cmd

    def find_command(ev: 'events.NewMessage.Event'):
        me = ev.client.me
        username = None if me is None else me.username

        for ent, txt in ev.message.get_entities_text():
            if isinstance(ent, MessageEntityBotCommand) and ent.offset == 0 and \
              (txt == cmd or (username is not None and txt.endswith(f'@{username}') and txt[:-len(username) - 1] == cmd)):
                ev.cmd = ent
                argparser.prog = txt        # command name setting in response messages
                args = argparser.convert_arg_line_to_args(ev.message.message[len(txt)+1:])
                try:
                    ev.args = argparser.parse_args(args)
                except ArgParserExit:
                    # it was that command but it failed, let's show fail message and don't call cmd callback
                    ev.client.loop.create_task(ev.reply(argparser.consume_messages()))
                    return False
                return True
        return False

    return find_command


def parse_time_interval(time_string):
    # TODO: better time parsing
    # https://github.com/scrapinghub/dateparser/issues/669
    # dt = dateparser.parse(time_string, settings={'PARSERS': ['relative-time']})
    # return abs(int((datetime.datetime.now() - dt).total_seconds())) if dt is not None else None
    return durations_nlp.Duration(time_string).to_seconds()


def yaml_constructor(tag: str, loader=yaml.SafeLoader):
    def reg(func):
        loader.add_constructor(tag, func)
        return func
    return reg


class YAMLRemapper(object):
    # You shouldn't even ask xDD
    def __init__(self, loader=yaml.SafeLoader):
        self.loader = loader
        self.yaml_remappers: List[Callable[[yaml.Event], Generator[ClassVar[yaml.Event], None, None]]] = []

    def yaml_remapper(self):
        def dec(func: 'Callable[[Generator[yaml.Event, None, None]], Generator[yaml.Event, None, None]]'):
            self.yaml_remappers.append(func)
            return func
        return dec

    def parse(self, stream):
        event_gen = yaml.parse(stream, self.loader)
        for remapper in self.yaml_remappers:
            event_gen = remapper(event_gen)
        yield from event_gen

    def load(self, stream):
        # Yes.. I know.. I've not found how to deserialize events
        yaml_events = self.parse(stream)
        yaml_unparsed = yaml.emit(yaml_events)
        return yaml.load(yaml_unparsed, self.loader)
