import argparse
import logging
import shlex

import durations_nlp
from telethon.tl.types import MessageEntityBotCommand
import telethon
import yaml

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, IO, Text, NoReturn, Union, Callable, ClassVar, Generator, List
    from telethon import events, types


logger = logging.getLogger(__name__)


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


class ArgumentParserExit(Exception):
    pass


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super(ArgumentParser, self).__init__(*args, **kwargs)
        self._messages = []

    @staticmethod
    def convert_arg_line_to_args(arg_line: 'Text', start: int = 0):
        parser = shlex.shlex(arg_line[start:], )
        parser.whitespace_split = True
        parser.commenters = ''
        # same behaviour as shlex.split

        edges = [start]
        args = []
        for arg in parser:
            edges.append(parser.instream.tell()+start)
            args.append(arg)
        return args, edges

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


class Argument(str):
    """
    Simple string able to hold MessageEntity and pass it through ArgumentParser
    """
    def __init__(self, *args, msg_entities=None, **kwargs):
        # super(Argument, self).__init__(*args, **kwargs)
        self.msg_entities = list(msg_entities) if msg_entities is not None else []


def command(cmd: str, argparser: 'Optional[ArgumentParser]' = None):
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
        argparser = ArgumentParser()
    cmd = cmd if cmd.startswith("/") else "/" + cmd

    def find_command(ev: 'events.NewMessage.Event'):
        me = ev.client.me
        username = None if me is None else me.username

        try:
            for ent, txt in ev.get_entities_text():
                if isinstance(ent, MessageEntityBotCommand) and ent.offset == 0 and \
                  (txt == cmd or (username is not None and txt.endswith(f'@{username}') and txt[:-len(username) - 1] == cmd)):
                    ev.cmd = ent
                    argparser.prog = txt        # command name setting in response messages

                    args, edges = argparser.convert_arg_line_to_args(ev.message.message, len(txt)+1)
                    args = [Argument(a) for a in args]

                    # matching of MessageEntities for arguments and pushing them through ArgumentParser
                    # THEY WILL GET LOST WHEN YOU WILL MAKE ARGPARSE CAST THEM!
                    for entity in ev.entities:
                        for i, edge in enumerate(edges[:-1]):
                            if edge <= entity.offset < edges[i+1] or edge < entity.offset + entity.length < edges[i+1]:
                                # is it valid? @up
                                args[i].msg_entities.append(entity)

                    # but they will be here even if you cast them ;)
                    ev.raw_args = args

                    try:
                        ev.args = argparser.parse_args(args)
                    except ArgumentParserExit:
                        # it was that command but it failed, let's show fail message and don't call cmd callback
                        ev.client.loop.create_task(ev.reply(argparser.consume_messages()))
                        return False
                    return True
        except Exception as e:
            ev.client.loop.create_task(ev.reply(repr(e)))
            logger.debug('Error in parsing command', exc_info=True)
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
