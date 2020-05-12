import logging
from io import StringIO

import durations_nlp
import telethon

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Union, Callable, Awaitable, Any
    from telethon import types


logger = logging.getLogger(__name__)


class Namespace(dict):
    def __getattr__(self, *args, **kwargs):
        return self.__getitem__(*args, **kwargs)


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


def parse_time_interval(time_string):
    # TODO: better time parsing
    # https://github.com/scrapinghub/dateparser/issues/669
    # dt = dateparser.parse(time_string, settings={'PARSERS': ['relative-time']})
    # return abs(int((datetime.datetime.now() - dt).total_seconds())) if dt is not None else None
    return durations_nlp.Duration(time_string).to_seconds()


async def cut_message_and_send(send_func: 'Callable[[str], Awaitable[Any]]', message: str, max_length: int = 4096) -> None:
    messages = [StringIO()]
    curr_msg = 0

    def msg():
        return messages[curr_msg]

    def new_msg():
        nonlocal curr_msg
        curr_msg += 1
        messages.append(StringIO())

    for line in message.splitlines(keepends=True):
        # line needs splitting
        word = None
        rest = [line]
        while len(rest):
            if msg().tell() + len(rest[0]) <= max_length:
                # line/rest of it fits in current message
                msg().write(rest.pop())
                continue
            elif len(rest[0]) <= max_length:
                # line/rest of it fits in new message
                new_msg()
                msg().write(rest.pop())
                continue

            word, *rest = rest[0].replace('\t', ' ', 1).split(' ', maxsplit=1)
            if msg().tell() + len(word) <= max_length:
                # word fits in current message
                msg().write(word)
                if msg().tell() + 1 <= max_length:
                    msg().write(" ")
            elif len(word) + 1 <= max_length:
                # word fits in new message
                new_msg()
                msg().write(word)
                msg().write(" ")
            else:
                # cut inside word if it still doesn't fit
                length = max_length - msg().tell()
                msg().write(word[:length])
                wrest = word[length:]
                rest = [(wrest + " " + rest[0]) if len(rest) else wrest]

    for m in messages:
        await send_func(m.getvalue())
