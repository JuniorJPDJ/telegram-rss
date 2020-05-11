import argparse
import logging
import shlex

import durations_nlp
from telethon.tl.types import MessageEntityBotCommand
from telethon.tl.custom.message import Message
import telethon
import yaml

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, IO, Text, NoReturn, Union, Callable, ClassVar, Generator, List
    from telethon import events, types
    from telethon.tl.types import TypeMessageEntity


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


class Argument(str):
    """
    Simple string able to hold MessageEntity and pass it through ArgumentParser
    """
    def __init__(
        self, *args, msg_entities: 'Optional[List[TypeMessageEntity]]' = None,
        start: 'Optional[int]' = None, end: 'Optional[int]' = None, **kwargs
    ):
        # super(Argument, self).__init__(*args, **kwargs)
        self.msg_entities = list(msg_entities) if msg_entities is not None else []
        self.start, self.end = start, end


class Command(ArgumentParser):
    def __init__(self, prog: str, parents=[], add_help: bool = True, **kwargs):
        """
        Parses command `prog` from Telegram message using `argparser`

        Pass instance of this class as `func` argument for NewMessage event in event handler decorator
        It will handle commands in format `/prog` and `/prog@bot_username` and set `event.cmd` to corresponding `CalledCommand`
        It will NOT handle commands inside messages, just in start of message!

        :param prog:    command phrase/name
        :param type:    the same as in argparse.ArgumentParse, but..
        If you'll use type not created for this purpose you will lose MessageEntity information from arguments
        """
        super(Command, self).__init__(parents=parents, add_help=add_help, **kwargs)

        self.prog = prog if prog.startswith("/") else "/" + prog
        self._kwargs = kwargs

    def __call__(self, ev: 'events.NewMessage.Event'):
        me = ev.client.me
        username = None if me is None else me.username

        try:
            for ent, txt in ev.get_entities_text():
                if isinstance(ent, MessageEntityBotCommand) and ent.offset == 0 and (
                    txt == self.prog or (
                        username is not None and txt.endswith(f'@{username}') and
                        txt[:-len(username) - 1] == self.prog
                    )
                ):
                    ev.cmd = cmd = CalledCommand(self, txt, ev.message)

                    try:
                        cmd.parse_args()
                    except ArgumentParserExit:
                        # it was that command but it failed, let's show fail message and don't call cmd callback
                        ev.client.loop.create_task(ev.reply(cmd.consume_messages()))
                        return False
                    return True
        except Exception as e:
            ev.client.loop.create_task(ev.reply(repr(e)))
            logger.debug('Error in parsing command', exc_info=True)
        return False


class CalledCommand(Command):
    # It's threadsafe!
    def __init__(self, cmd: Command, prog: str, msg: Message):
        super(CalledCommand, self).__init__(prog=prog, add_help=False, parents=[cmd], **cmd._kwargs)

        self.raw_args = self.args = self.bounds = None
        self.msg, self.text = msg, msg.message

    def convert_arg_line_to_args(self):
        start = len(self.prog)+1

        parser = shlex.shlex(self.text[start:])
        parser.whitespace_split = True
        parser.commenters = ''
        # same behaviour as shlex.split

        bounds = [start]
        args = []
        for arg in parser:
            _arg = Argument(arg)
            _arg.start = bounds[-1]

            end = parser.instream.tell() + start
            _arg.end = end - 1
            bounds.append(end)

            args.append(_arg)

        self.raw_args = args
        self.bounds = bounds

        # matching of MessageEntities to arguments for pushing them through ArgumentParser
        # THEY WILL GET LOST WHEN YOU WILL MAKE ARGPARSE CAST THEM AND TYPE DOESN'T KNOW IT SHOULD CARE ABOUT IT!
        for entity in self.msg.entities:
            #for i, bound in enumerate(bounds[:-1]):
            for a in args:
                if a.start <= entity.offset <= a.end or a.start < entity.offset + entity.length < a.end:
                    # is it valid? @up
                    a.msg_entities.append(entity)

        return args

    def parse_args(self) -> Namespace:
        self.args = Namespace(
            super(CalledCommand, self).parse_args(
                self.convert_arg_line_to_args()
            ).__dict__
        )

        return self.args


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
