#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from collections import defaultdict
from time import sleep
from typing import Dict, List, Union
from pathlib import Path

import feedparser
import msgpack
import telegram
import yaml
import bs4
from telegram.ext import Updater, CommandHandler, Dispatcher

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

history = {}
tg_chats = {}
config = None
datadir = None


def save_data():
    with open(datadir / 'tg_chats.msgp', "wb") as f:
        msgpack.pack(tg_chats, f)

    with open(datadir / 'history.msgp', "wb") as f:
        msgpack.pack(history, f)


def subcmd(bot, update, args):
    if not len(args):
        update.message.reply_text("Syntax error\nSyntax: /subscribe URL [title]")
        return
    url = args[0]
    feed = feedparser.parse(url)
    if "bozo_exception" in feed:
        update.message.reply_text("Error when trying to subscribe feed: {}".format(feed['bozo_exception']))
    else:
        if len(args) > 1:
            title = " ".join(args[1:])
        elif 'channel' in feed and 'title' in feed['channel']:
            title = feed['channel']['title']
        else:
            title = url

        tg_chats[url][update.effective_chat.id] = {'title': title}
        for entry in feed["entries"]:
            id_ = entry["id"] if "id" in entry else entry['link'] if 'link' in entry else entry['title']
            if id_ not in history[url]:
                history[url].append(id_)

        update.message.reply_text('Subscribed feed "{}" - now new messsages from this feed will appear in this chat!'.format(title))
        save_data()


def listcmd(bot, update):
    urls = {}
    chatid = update.effective_chat.id
    for url in tg_chats:
        if chatid in tg_chats[url]:
            urls[url] = tg_chats[url][chatid]["title"]

    if urls:
        msg = "Subscribed feeds on this chat:"
        for url in urls:
            msg = "{}\n\n{}: {}".format(msg, urls[url], url)
    else:
        msg = "No feeds subscribed on this chat."

    update.message.reply_text(msg)


def unsubcmd(bot, update, args):
    if not len(args):
        update.message.reply_text("Syntax error.\nSyntax: /unsubscribe URL")
        return

    chatid = update.effective_chat.id
    url = args[0]
    if url in tg_chats and chatid in tg_chats[url]:
        title = tg_chats[url][chatid]['title']
        del tg_chats[url][chatid]
        update.message.reply_text('Successfully unsubscribed feed with title "{}"!'.format(title))
    else:
        update.message.reply_text("No feed found")


def error(bot, update, error):
    logger.warning('Update "%s" caused error "%s"', update, error)


def download_feed(dispatcher: Dispatcher, url):
    feed = feedparser.parse(url)

    for entry in feed["entries"]:
        id_ = entry["id"] if "id" in entry else entry['link'] if 'link' in entry else entry['title']
        if id_ not in history[url]:

            desc = bs4.BeautifulSoup(entry['description'], features="html.parser").get_text() if 'description' in entry else ''
            title = entry['title']
            link = entry['link'] if 'link' in entry else url
            for chat in tg_chats[url]:
                feedtitle = tg_chats[url][chat]['title']
                chat = dispatcher.bot.get_chat(chat)

                msg = config['msg_template'].format(url=link, feedtitle=feedtitle, desc=desc, title=title)
                chat.send_message(msg, parse_mode=telegram.ParseMode.MARKDOWN)
            history[url].append(id_)


def feed_loop(dispatcher: Dispatcher, check_time):
    for url in tg_chats:
        if not tg_chats[url]:
            continue

        dispatcher.run_async(download_feed, dispatcher, url)

    sleep(check_time)
    dispatcher.run_async(feed_loop, dispatcher, check_time)


def main():
    global config
    global history
    global tg_chats
    global datadir

    with open("config.yml", 'r') as f:
        config = yaml.safe_load(f)
        if config is None or 'tg_bot_token' not in config:
            raise Exception("Config is not valid")

    datadir = Path(config['datadir'])

    try:
        with open(datadir / "tg_chats.msgp", "rb") as f:
            tg_chats = msgpack.unpack(f, raw=False)
    except FileNotFoundError:
        tg_chats = {}

    try:
        with open(datadir / "history.msgp", "rb") as f:
            history = msgpack.unpack(f, raw=False)
    except FileNotFoundError:
        history = {}

    history = defaultdict(list, history)  # type: Dict[str, List[str]]
    tg_chats = defaultdict(dict, tg_chats)  # type: Dict[str, Dict[str, Union[str, List[int]]]]
    # {url: {chatid: {'title': str}}

    updater = Updater(config['tg_bot_token'])

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("subscribe", subcmd, pass_args=True))
    dp.add_handler(CommandHandler("list", listcmd))
    dp.add_handler(CommandHandler("unsubscribe", unsubcmd, pass_args=True))
    dp.add_error_handler(error)
    updater.start_polling()

    dp.run_async(feed_loop, dp, config['check_interval'])

    updater.idle()

    save_data()


if __name__ == '__main__':
    main()
