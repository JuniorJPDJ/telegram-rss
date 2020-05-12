import os

import yaml
import yaml.resolver

from utils import parse_time_interval, Namespace
from utils.config_utils import yaml_constructor, YAMLRemapper


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Generator


@yaml_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG)
def namespace_constructor(loader, node):
    loader.flatten_mapping(node)
    return Namespace(loader.construct_pairs(node))


@yaml_constructor('!time')
def time_constructor(loader, node):
    return parse_time_interval(loader.construct_scalar(node))


@yaml_constructor("!env")
def env_constructor(loader, node):
    return os.environ.get(loader.construct_scalar(node), None)


# handling of env var YAML in YAML
yamlremapper = YAMLRemapper()


@yamlremapper.yaml_remapper()
def yamlenv_remapper(events: 'Generator[yaml.Event, None, None]') -> 'Generator[yaml.Event, None, None]':
    for event in events:
        if isinstance(event, yaml.ScalarEvent) and event.tag == '!yamlenv':
            data = os.environ.get(event.value, "")
            data = data if data else "sOmErAnDomStRiNg:"

            started = False
            for internal_event in yamlremapper.parse(data):
                if isinstance(internal_event, yaml.DocumentEndEvent):
                    break
                elif started:
                    yield internal_event
                elif isinstance(internal_event, yaml.DocumentStartEvent):
                    started = True
        else:
            yield event
