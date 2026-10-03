"""Durable immutable agent journal and transaction boundary for paper accounts."""
from __future__ import annotations

import contextlib
import json
import math
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from .models import AgentMessage, SECRET_FIELDS, STAGES


_PREVIOUS = {'request': None, 'data': 'request', 'quant': 'data', 'risk': 'quant',
             'approval': 'risk', 'execution': 'approval'}
_SENSITIVE = set(SECRET_FIELDS) | {'dart_api_key', 'secret', 'credentials'}


def safe_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', value):
        raise ValueError('Identifier must contain only safe characters and at most 80 characters')
    return value


def _safe_json(value):
    def check(item, depth=0):
        if depth > 64:
            raise ValueError('Journal JSON nesting exceeds the supported depth')
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or key.lower() in _SENSITIVE:
                    raise ValueError('Journal cannot persist credential fields or nonstring object keys')
                check(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check(child, depth + 1)
    check(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, OverflowError, UnicodeError):
        raise ValueError('Journal requires strict finite JSON') from None


def normalize_portfolio(value):
    if not isinstance(value, dict) or set(value) != {'cash', 'positions'} or not isinstance(value['positions'], dict):
        raise ValueError('Paper portfolio requires cash and a quantity map')
    def number(raw):
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0:
            raise ValueError('Paper portfolio amounts must be nonnegative finite numbers')
        return float(raw)
    positions = {}
    for symbol, raw in value['positions'].items():
        if not isinstance(symbol, str) or not re.fullmatch(r'\d{6}', symbol):
            raise ValueError('Paper positions require six-digit stock symbols')
        quantity = number(raw)
        if quantity:
            positions[symbol] = quantity
    return dict(cash=number(value['cash']), positions=positions)


def iso_date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('Paper dates must use YYYY-MM-DD')
    return value


class AgentStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, report_json TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_stages (
                    run_id TEXT NOT NULL REFERENCES agent_runs(run_id), stage TEXT NOT NULL,
                    message_id TEXT NOT NULL, message_json TEXT NOT NULL,
                    PRIMARY KEY(run_id,stage)
                );
                CREATE TABLE IF NOT EXISTS agent_errors (
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
                    stage TEXT NOT NULL, error_type TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_accounts (
                    account_id TEXT PRIMARY KEY, cash REAL NOT NULL CHECK(cash>=0),
                    positions_json TEXT NOT NULL, last_execution_date TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_executions (
                    account_id TEXT NOT NULL REFERENCES paper_accounts(account_id), execution_date TEXT NOT NULL,
                    run_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(run_id),
                    approval_message_id TEXT NOT NULL, message_json TEXT NOT NULL,
                    PRIMARY KEY(account_id,execution_date)
                );
                CREATE TABLE IF NOT EXISTS paper_fills (
                    run_id TEXT NOT NULL REFERENCES agent_runs(run_id), fill_index INTEGER NOT NULL,
                    fill_json TEXT NOT NULL, PRIMARY KEY(run_id,fill_index)
                );
            ''')

    @contextlib.contextmanager
    def _connection(self):
        connection = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=30000')
        connection.execute('PRAGMA synchronous=FULL')
        try:
            yield connection
        finally:
            connection.close()

    @contextlib.contextmanager
    def _transaction(self):
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _require_run(connection, run_id):
        if connection.execute('SELECT 1 FROM agent_runs WHERE run_id=?', (run_id,)).fetchone() is None:
            raise ValueError('Run must be registered before writing a journal entry')

    def begin_run(self, run_id, request_hash):
        safe_identifier(run_id)
        if not isinstance(request_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', request_hash):
            raise ValueError('Request identity must be a canonical SHA256 digest')
        with self._transaction() as connection:
            row = connection.execute('SELECT request_hash FROM agent_runs WHERE run_id=?', (run_id,)).fetchone()
            if row is not None and row['request_hash'] != request_hash:
                raise ValueError('Run identity cannot be reused with a different request')
            if row is None:
                connection.execute('INSERT INTO agent_runs(run_id,request_hash) VALUES(?,?)', (run_id, request_hash))

    def load_stage(self, run_id, stage):
        safe_identifier(run_id)
        if stage not in STAGES:
            raise ValueError('Unsupported journal stage')
        with self._connection() as connection:
            row = connection.execute('SELECT message_json,message_id FROM agent_stages WHERE run_id=? AND stage=?', (run_id, stage)).fetchone()
            registered = connection.execute('SELECT request_hash FROM agent_runs WHERE run_id=?', (run_id,)).fetchone() if stage == 'request' else None
        if row is None:
            return None
        value = json.loads(row['message_json'])
        parsed = AgentMessage.from_dict(value)
        if parsed.run_id != run_id or parsed.stage != stage or parsed.message_id != row['message_id']:
            raise ValueError('Stored message does not match its journal identity')
        if stage == 'request' and (registered is None or registered['request_hash'] != parsed.message_id):
            raise ValueError('Stored request does not match the registered run identity')
        return value

    @staticmethod
    def _save_stage(connection, run_id, stage, message):
        parsed = AgentMessage.from_dict(message)
        if parsed.run_id != run_id or parsed.stage != stage:
            raise ValueError('Message identity does not match its journal stage')
        serialized = _safe_json(message)
        AgentStore._require_run(connection, run_id)
        previous = _PREVIOUS[stage]
        if previous:
            row = connection.execute('SELECT message_id,message_json FROM agent_stages WHERE run_id=? AND stage=?', (run_id, previous)).fetchone()
            if row is None:
                raise ValueError('Journal stage requires its completed predecessor')
            parent = AgentMessage.from_dict(json.loads(row['message_json']))
            if parent.run_id != run_id or parent.stage != previous or row['message_id'] != parent.message_id or parent.message_id != parsed.parent_id:
                raise ValueError('Message parent does not match the stored previous stage')
            if any(key not in parsed.payload or _safe_json(parsed.payload[key]) != _safe_json(value)
                   for key, value in parent.payload.items()):
                raise ValueError('A child journal stage cannot rewrite upstream evidence')
        elif parsed.parent_id is not None:
            raise ValueError('Request message cannot have a parent')
        if stage == 'request':
            run = connection.execute('SELECT request_hash FROM agent_runs WHERE run_id=?', (run_id,)).fetchone()
            if run['request_hash'] != parsed.message_id:
                raise ValueError('Request message digest does not match the registered run identity')
        row = connection.execute('SELECT message_json FROM agent_stages WHERE run_id=? AND stage=?', (run_id, stage)).fetchone()
        if row is not None:
            if row['message_json'] != serialized:
                raise ValueError('A completed journal stage is immutable')
            return
        connection.execute('INSERT INTO agent_stages(run_id,stage,message_id,message_json) VALUES(?,?,?,?)',
                           (run_id, stage, parsed.message_id, serialized))

    def save_stage(self, run_id, stage, message):
        safe_identifier(run_id)
        if stage not in STAGES:
            raise ValueError('Unsupported journal stage')
        with self._transaction() as connection:
            self._save_stage(connection, run_id, stage, message)

    def load_report(self, run_id):
        safe_identifier(run_id)
        with self._connection() as connection:
            row = connection.execute('SELECT report_json FROM agent_runs WHERE run_id=?', (run_id,)).fetchone()
        return json.loads(row['report_json']) if row is not None and row['report_json'] is not None else None

    def save_report(self, run_id, report):
        safe_identifier(run_id)
        if not isinstance(report, dict):
            raise ValueError('Run report must be a JSON object')
        serialized = _safe_json(report)
        with self._transaction() as connection:
            self._require_run(connection, run_id)
            row = connection.execute('SELECT report_json FROM agent_runs WHERE run_id=?', (run_id,)).fetchone()
            if row['report_json'] is not None and row['report_json'] != serialized:
                raise ValueError('A completed run report is immutable')
            connection.execute('UPDATE agent_runs SET report_json=? WHERE run_id=?', (serialized, run_id))

    def record_error(self, run_id, stage, error_type):
        safe_identifier(run_id)
        if stage not in STAGES:
            raise ValueError('Unsupported journal stage')
        name = error_type if isinstance(error_type, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', error_type) else 'Error'
        with self._transaction() as connection:
            self._require_run(connection, run_id)
            connection.execute('INSERT INTO agent_errors(run_id,stage,error_type,created_at) VALUES(?,?,?,?)',
                (run_id, stage, name, datetime.now(timezone.utc).isoformat()))

    @staticmethod
    def _account(connection, account_id):
        row = connection.execute('SELECT cash,positions_json,last_execution_date FROM paper_accounts WHERE account_id=?', (account_id,)).fetchone()
        if row is None:
            return None, None
        return normalize_portfolio(dict(cash=row['cash'], positions=json.loads(row['positions_json']))), row['last_execution_date']

    def load_account(self, account_id):
        safe_identifier(account_id)
        with self._connection() as connection:
            account, _ = self._account(connection, account_id)
        return account

    def execute_paper(self, *, run_id, account_id, execution_date, supplied_portfolio,
                      approval_message_id, build_message):
        """Commit fills, account, immutable execution stage and daily slot together.

        A callback computes a paper result inside the write transaction. It has no
        broker side effects. Any failure rolls back all persistent trading state.
        """
        safe_identifier(run_id)
        safe_identifier(account_id)
        iso_date(execution_date)
        supplied = normalize_portfolio(supplied_portfolio)
        with self._transaction() as connection:
            self._require_run(connection, run_id)
            previous = connection.execute('SELECT * FROM paper_executions WHERE run_id=?', (run_id,)).fetchone()
            if previous is not None:
                if (previous['account_id'], previous['execution_date'], previous['approval_message_id']) != (account_id, execution_date, approval_message_id):
                    raise ValueError('Paper execution identity cannot change on replay')
                message = json.loads(previous['message_json'])
                AgentMessage.from_dict(message)
                return dict(status='replayed', message=message)
            account, last_date = self._account(connection, account_id)
            occupied = connection.execute('SELECT run_id,message_json FROM paper_executions WHERE account_id=? AND execution_date=?',
                                           (account_id, execution_date)).fetchone()
            if occupied is not None:
                daily = AgentMessage.from_dict(json.loads(occupied['message_json']))
                result = daily.payload['execution']
                if (daily.run_id != occupied['run_id'] or daily.stage != 'execution' or result['status'] != 'executed'
                        or result['account_id'] != account_id or result['date'] != execution_date):
                    raise ValueError('Occupied daily result does not match the paper account and date')
                return dict(status='duplicate_day', portfolio=normalize_portfolio(result['portfolio']))
            if account is not None and (supplied != account or execution_date <= last_date):
                raise ValueError('Supplied paper portfolio is stale or execution dates are out of order')
            state = supplied if account is None else account
            message = build_message(state)
            parsed = AgentMessage.from_dict(message)
            if parsed.run_id != run_id or parsed.stage != 'execution' or parsed.parent_id != approval_message_id:
                raise ValueError('Paper result has an invalid execution identity')
            result = parsed.payload['execution']
            if result['status'] != 'executed' or result['account_id'] != account_id or result['date'] != execution_date:
                raise ValueError('Paper result does not match the reserved account and date')
            updated = normalize_portfolio(result['portfolio'])
            serialized = _safe_json(message)
            connection.execute('INSERT INTO paper_accounts(account_id,cash,positions_json,last_execution_date) VALUES(?,?,?,?) '
                'ON CONFLICT(account_id) DO UPDATE SET cash=excluded.cash,positions_json=excluded.positions_json,last_execution_date=excluded.last_execution_date',
                (account_id, updated['cash'], _safe_json(updated['positions']), execution_date))
            connection.execute('INSERT INTO paper_executions(account_id,execution_date,run_id,approval_message_id,message_json) VALUES(?,?,?,?,?)',
                (account_id, execution_date, run_id, approval_message_id, serialized))
            for index, fill in enumerate(result['fills']):
                connection.execute('INSERT INTO paper_fills(run_id,fill_index,fill_json) VALUES(?,?,?)', (run_id, index, _safe_json(fill)))
            self._save_stage(connection, run_id, 'execution', message)
            return dict(status='executed', message=message)
