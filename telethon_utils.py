import asyncio
from argparse import ArgumentParser, Namespace
import shlex

from telethon.tl.types import MessageEntityBotCommand
from telethon import TelegramClient

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, IO, Text, NoReturn, Sequence, Union
    from telethon import events

# Yes, I know how it looks like, but I couldn't find another way to get own username in sync function
# Still waiting for this issue to resolve this problem:
# https://github.com/LonamiWebs/Telethon/issues/1344
# <sync user getting hooks>
getme = TelegramClient.get_me
async def newgetme(self, input_peer=False):
    ret = await getme(self, input_peer)
    if not input_peer:
        self.me = ret
    return ret
TelegramClient.get_me = newgetme

start = TelegramClient._start
async def newstart(self, phone, password, bot_token, force_sms, code_callback, first_name, last_name, max_attempts):
    ret = await start(self, phone, password, bot_token, force_sms, code_callback, first_name, last_name, max_attempts)
    await self.get_me()
    return ret
TelegramClient._start = newstart
# </sync user getting hooks>


class ArgParserExit(Exception):
    pass


class ArgParser(ArgumentParser):
    def __init__(self, *args, **kwargs):
        super(ArgParser, self).__init__(*args, **kwargs)
        self._messages = []

    # def parse_args(self, args: 'Optional[Union[Sequence[Text], Text]]' = ...) -> Namespace:
    #     if isinstance(args, str):
    #         args = shlex.split(args)
    #     return super(ArgParser, self).parse_args(args)

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
        username = '' if me is None else me.username

        for ent, txt in ev.message.get_entities_text():
            if isinstance(ent, MessageEntityBotCommand) and ent.offset == 0 and \
              (txt == cmd or (txt.endswith(f'@{username}') and txt[:-len(username) - 1] == cmd)):
                ev.cmd = ent
                # workaround for fail message
                argparser.prog = txt
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
