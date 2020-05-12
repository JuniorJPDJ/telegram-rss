from urllib.parse import urlparse, parse_qs

from telethon.tl.types import MessageEntityMentionName, MessageEntityTextUrl, MessageEntityMention, MessageEntityUrl

from utils.command_utils import Argument


from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from typing import Dict, Callable, Text, Union
    from telethon.tl.types import TypeMessageEntity


# Thank you https://github.com/LonamiWebs/Telethon/wiki/Special-links
HOSTNAMES = ("telegram.me", "t.me", "telegram.dog", "telesco.pe")
FORBIDDEN_HTTP_PATHES = ("/joinchat", "/addstickers", "/iv", "/msg", "/share", "/confirmphone", "/start",
                         "/startgroup", "/game", "/socks", "/proxy", "/setlanguage", "/bg")


class TelegramArgument(object):
    def __init__(self, arg: Argument):
        self.arg = arg

    @property
    def msg_entities(self):
        return self.arg.msg_entities


class ChatTarget(TelegramArgument):
    MessageEntityChatExtractors: \
        'Dict[Type[TypeMessageEntity], Callable[[ChatTarget, TypeMessageEntity], Union[Text, int]]]' = \
    {
        MessageEntityMentionName: lambda self, e: e.user_id,
        MessageEntityMention: lambda self, e: self.arg.cmd.text[e.offset+1:e.offset + e.length],
        MessageEntityTextUrl: lambda self, e: self._parse_url(e.url),
        MessageEntityUrl: lambda self, e: self._parse_url(self.arg.cmd.text[e.offset:e.offset + e.length]),
    }

    def __init__(self, arg: Argument):
        super(ChatTarget, self).__init__(arg)

        data = None
        for e in self.msg_entities:
            if e.__class__ in self.MessageEntityChatExtractors:
                data = self.MessageEntityChatExtractors[e.__class__](self, e)
                if data is not None:
                    break

        if data is None:
            # Allow just chat_id/entity_id
            # this cast already raise ValueError if not int
            data = int(arg)

        self.data = data

    async def get_entity(self):
        # real verification of ID/username occurs only here, so you need to be prepared for catching
        try:
            return await self.arg.cmd.msg.client.get_input_entity(self.data)
        except Exception as e:
            raise ValueError("Invalid chat target") from e

    def _parse_url(self, url):
        url = urlparse(url if "//" in url else "//" + url)

        if url.scheme == "tg":
            return self._parse_tg_url(url)
        elif url.scheme in ("http", "https", ""):
            return self._parse_http_url(url)

    @staticmethod
    def _parse_tg_url(url):
        # eg. tg://resolve?domain=rootnews
        if url.netloc != "resolve":
            raise ValueError("Bad Chat target")

        query = parse_qs(url.query)

        if "domain" not in query:
            raise ValueError("Bad Chat target")

        return query["domain"][0]

    @staticmethod
    def _parse_http_url(url):
        # eg. https://t.me/rootnews
        if url.hostname not in HOSTNAMES or not url.path:
            raise ValueError("Bad Chat target")

        for path in FORBIDDEN_HTTP_PATHES:
            if url.path.startswith(path):
                raise ValueError("Bad Chat target")

        return url.path.split("/")[1]
