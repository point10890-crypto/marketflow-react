"""Strict immutable JSON messages shared by the specialized trading agents."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field


STAGES = frozenset({'request', 'data', 'quant', 'risk', 'approval', 'execution'})
SECRET_FIELDS = frozenset({'api_key', 'crtfc_key', 'authorization', 'access_token', 'refresh_token',
                           'app_secret', 'kis_app_secret', 'client_secret', 'password'})


def _immutable(*_args, **_kwargs):
    raise TypeError('Agent message payloads are immutable snapshots')


class _FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, _memo):
        return json.loads(json.dumps(self, ensure_ascii=False, allow_nan=False))


class _FrozenList(list):
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, _memo):
        return json.loads(json.dumps(self, ensure_ascii=False, allow_nan=False))


def _freeze(value, depth=0):
    if depth > 64:
        raise ValueError('Agent message JSON nesting exceeds the supported depth')
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Agent messages require finite JSON numbers')
        return value
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError('Agent message JSON object keys must be strings')
        if any(key.lower() in SECRET_FIELDS for key in value):
            raise ValueError('Agent messages cannot contain secret fields')
        return _FrozenDict((key, _freeze(item, depth + 1)) for key, item in value.items())
    if isinstance(value, list):
        return _FrozenList(_freeze(item, depth + 1) for item in value)
    raise ValueError('Agent message payload must contain only strict JSON values')


@dataclass(frozen=True)
class AgentMessage:
    run_id: str
    stage: str
    payload: dict
    parent_id: str | None = None
    schema_version: int = 1
    _canonical_body: str = field(init=False, repr=False, compare=False)
    _message_id: str = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if not isinstance(self.run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', self.run_id):
            raise ValueError('run_id must be a safe identifier of at most 80 characters')
        if not isinstance(self.stage, str) or self.stage not in STAGES:
            raise ValueError('Unsupported agent message stage')
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int) or self.schema_version != 1:
            raise ValueError('Unsupported agent message schema version')
        if self.parent_id is not None and (not isinstance(self.parent_id, str) or not self.parent_id.strip()):
            raise ValueError('parent_id must be a nonempty message identifier or null')
        if not isinstance(self.payload, dict):
            raise ValueError('Agent message payload must be a JSON object')
        object.__setattr__(self, 'payload', _freeze(self.payload))
        try:
            canonical = json.dumps({'run_id': self.run_id, 'stage': self.stage, 'payload': self.payload,
                                    'parent_id': self.parent_id, 'schema_version': self.schema_version},
                                   sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, OverflowError, UnicodeError) as error:
            raise ValueError('Agent message cannot be represented as strict finite JSON') from error
        object.__setattr__(self, '_canonical_body', canonical)
        object.__setattr__(self, '_message_id', hashlib.sha256(canonical.encode('utf-8')).hexdigest())

    @property
    def message_id(self):
        return self._message_id

    def to_dict(self):
        return {'message_id': self.message_id, **json.loads(self._canonical_body)}

    @classmethod
    def from_dict(cls, value):
        required = {'message_id', 'run_id', 'stage', 'payload', 'parent_id', 'schema_version'}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError('Serialized agent message has an invalid schema or missing identifier')
        message = cls(value['run_id'], value['stage'], value['payload'], value['parent_id'], value['schema_version'])
        if value['message_id'] != message.message_id:
            raise ValueError('Agent message identifier does not match its content')
        return message


def create_message(run_id, stage, payload, parent_id=None):
    return AgentMessage(run_id=run_id, stage=stage, payload=payload, parent_id=parent_id)
