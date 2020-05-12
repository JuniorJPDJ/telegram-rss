import logging

import yaml

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Generator, List


logger = logging.getLogger(__name__)


def yaml_constructor(tag: str, loader=yaml.SafeLoader):
    def reg(func):
        loader.add_constructor(tag, func)
        return func
    return reg


class YAMLRemapper(object):
    # You shouldn't even ask xDD
    def __init__(self, loader=yaml.SafeLoader):
        self.loader = loader
        self.yaml_remappers: List[Callable[[Generator[yaml.Event, None, None]], Generator[yaml.Event, None, None]]] = []

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
