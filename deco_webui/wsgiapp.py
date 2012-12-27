# Copyright 2012 Stanford University InfoLab
# See LICENSE for details.

from gevent import monkey; monkey.patch_all()

import argparse
import beaker.middleware
from contextlib import closing
from datetime import datetime, timedelta
import functools
import getpass
import json
import logging
import os
import re
import sys
import tempfile

import bottle
import gevent
import geventwebsocket
import psycopg2

import deco
from deco_webui import __version__


session_opts = {
    'session.type': 'cookie',
    'session.key': 'deco.session',
    'session.validate_key': 'abcdef',
}
app = beaker.middleware.SessionMiddleware(bottle.app(), session_opts)

connect_kwargs = None

_cursors = {}


def _get_session():
    return bottle.request.environ.get('beaker.session')


def signed_in(func):
    @functools.wraps(func)
    def wrap(*args, **kwargs):
        session = _get_session()
        if 'user' in session:
            return func(*args, **kwargs)
        else:
            bottle.redirect('/signin')
    return wrap


def _connect():
    session = _get_session()
    try:
        conn = deco.connect(database=session['user'],
                            user=session['user'],
                            password=session['password'])
    except (KeyError, psycopg2.Error):
        raise RuntimeError('database connection failed')
    return conn


def _wrap_value(x):
    if x is None:
        y = {'v': x, 'f': 'NULL'}
    elif hasattr(x, 'isoformat'):
        y = {'v': x.isoformat()}
    else:
        y = {'v': unicode(x)}
    return y


def execute(ws, query):
    sqls = [x[:-1].strip() for x in re.findall(
        r"(?:[^';]|'(?:\\'|[^'])*')+[^;]*;",
        bottle.touni(query) + ';')]

    if len(sqls) > 1 and [1 for x in sqls if x[:6].upper() == 'SELECT']:
        ws.send(json.dumps(
            {'error': 'SELECT statements must be executed alone'}))
        return

    try:
        with _connect() as conn, closing(conn.cursor()) as cursor:
            def ws_send(action, row):
                if action == 'shift' or action == 'terminate':
                    ws.send(json.dumps({'a': action[0]}))
                else:  # populate, add, remove
                    wrapped_row = [_wrap_value(x) for x in row]
                    ws.send(json.dumps({'a': action[0], 'r': wrapped_row}))

            for sql in sqls:
                cursor.execute(sql, callback=ws_send)

            if cursor.description:
                session_id = _get_session()['_id']
                _cursors[session_id] = cursor
                ws.send(json.dumps(
                    {'a': 'd', 'c': [x[0] for x in cursor.description]}))
                cursor.fetchone()
                del _cursors[session_id]
            else:
                ws.send(json.dumps({'error': None}))

    # pylint: disable=W0703
    except (RuntimeError, deco.Error, psycopg2.Error, Exception) as e:
        ws.send(json.dumps({'error': unicode(e)}))


def executebackend(ws, query):
    sqls = [x[:-1].strip() for x in re.findall(
        r"(?:[^';]|'(?:\\'|[^'])*')+[^;]*;",
        bottle.touni(query) + ';')]

    if len(sqls) > 1 and [1 for x in sqls if x[:6].upper() == 'SELECT']:
        ws.send(json.dumps(
            {'error': 'SELECT statements must be executed alone'}))
        return

    try:
        with _connect() as conn, closing(conn.cursor()) as cursor:
            for sql in sqls:
                cursor._executebackend(sql)

            if cursor.description:
                ws.send(json.dumps(
                    {'a': 'd', 'c': [x[0] for x in cursor.description]}))
                for row in cursor:
                    wrapped_row = [_wrap_value(x) for x in row]
                    ws.send(json.dumps({'a': 'p', 'r': wrapped_row}))
                ws.send(json.dumps({'a': 's'}))
                ws.send(json.dumps({'a': 't'}))
            else:
                ws.send(json.dumps({'error': None}))

    except (RuntimeError, psycopg2.Error) as e:
        ws.send(json.dumps({'error': unicode(e)}))


@bottle.route('/websocket')
def websocket():
    ws = bottle.request.environ.get('wsgi.websocket')
    if ws:
        try:
            while True:
                message = ws.receive()
                if message is None:
                    break
                elif message[0] == 'b':
                    executebackend(ws, message[1:])
                elif message[0] == 'd':
                    execute(ws, message[1:])
        except geventwebsocket.WebSocketError as e:
            sys.stderr.write(unicode(e) + '\n')
        finally:
            ws.close()
    else:
        bottle.abort(400, 'Bad Request')


class _WebSocketHandler(logging.Handler):

    def __init__(self, ws):
        super(_WebSocketHandler, self).__init__()
        self.ws = ws

    def emit(self, record):
        self.ws.send(json.dumps(
            [record.asctime, record.levelname, record.message]))


@bottle.route('/log')
def log():
    ws = bottle.request.environ.get('wsgi.websocket')
    if ws:
        handler = _WebSocketHandler(ws)
        handler.setLevel(logging.INFO)
        logging.root.addHandler(handler)

        try:
            while True:
                message = ws.receive()
                if message is None:
                    break
        except geventwebsocket.WebSocketError as e:
            sys.stderr.write(unicode(e) + '\n')
        finally:
            logging.root.removeHandler(handler)
            ws.close()
    else:
        bottle.abort(400, 'Bad Request')


@bottle.get('/stopexecution')
def stopexecution():
    session_id = _get_session()['_id']
    cursor = _cursors.get(session_id)
    if cursor:
        cursor._stopexecution()


@bottle.post('/explain')
def explain():
    sqls = [x[:-1].strip() for x in re.findall(
        r"(?:[^';]|'(?:\\'|[^'])*')+[^;]*;",
        bottle.touni(bottle.request.forms.get('query')) + ';')]

    if len(sqls) > 1:
        return {'error': 'only one SELECT statement can be explained'}
    elif len(sqls) == 0:
        return {'error': None, 'plan': None}

    try:
        with _connect() as conn, closing(conn.cursor()) as cursor:
            plan = cursor._explain(sqls[0], True)
        error = None
    except (RuntimeError, deco.Error, psycopg2.Error) as e:
        error = unicode(e)
        plan = None

    return {'error': error, 'plan': plan}


@bottle.get('/static/:path#.+#')
def static(path):
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    bottle.response.headers['Cache-Control'] = 'public, max-age=31536000'
    if path.endswith('.css') or path.endswith('.js'):
        bottle.response.headers['Vary'] = 'Accept-Encoding'
        if 'gzip' in bottle.request.headers.get('Accept-Encoding'):
            gzipped = bottle.static_file(path + '.gz', root=static_dir)
            if isinstance(gzipped, bottle.HTTPResponse):
                return gzipped
    return bottle.static_file(path, root=static_dir)


@bottle.get('/')
@signed_in
@bottle.jinja2_view(
    os.path.join(os.path.dirname(__file__), 'templates', 'index.html'))
def index():
    session = _get_session()
    database = session.get('user')
    return dict(database=database, version=__version__)


@bottle.get('/signin')
@bottle.jinja2_view(
    os.path.join(os.path.dirname(__file__), 'templates', 'signin.html'))
def signin():
    session = _get_session()
    error_message = session.get('error', '')
    session.delete()
    session.save()
    return dict(error=error_message)


@bottle.post('/signin')
def do_signin():
    session = _get_session()
    user = bottle.request.forms.get('user')
    password = bottle.request.forms.get('pass')

    if not user or not password:
        session['error'] = 'Both username and password are required.'
        session.save()
        bottle.redirect('/signin')

    try:
        conn = deco.connect(database=user, user=user, password=password)
    except psycopg2.Error as e:
        if 'authentication failed' in unicode(e):
            session['error'] = 'Password authentication failed.'
        elif 'does not exist' in unicode(e):
            session['error'] = 'Username does not exist.'
        else:
            session['error'] = unicode(e)
        session.save()
        bottle.redirect('/signin')
    else:
        conn.close()

    session['user'] = user
    session['password'] = password
    if bottle.request.forms.get('remember'):
        session['_expires'] = datetime.utcnow() + timedelta(days=7)
    session.save()
    bottle.redirect('/')


@bottle.get('/signout')
@signed_in
def signout():
    session = _get_session()
    session.invalidate()
    session.save()
    bottle.redirect('/signin')


@bottle.get('/signup')
@bottle.jinja2_view(
    os.path.join(os.path.dirname(__file__), 'templates', 'signup.html'))
def signup():
    session = _get_session()
    error_message = session.get('error', '')
    session.delete()
    session.save()
    return dict(error=error_message)


@bottle.post('/signup')
def do_signup():
    session = _get_session()
    user = bottle.request.forms.get('user')
    password = bottle.request.forms.get('pass')
    password2 = bottle.request.forms.get('pass2')

    if not user or not password or not password2:
        session['error'] = 'All fields are required.'
    elif password != password2:
        session['error'] = 'Passwords do not match.'
    elif len(user) > 16:
        session['error'] = 'Username is too long.'
    elif len(password) > 32:
        session['error'] = 'Password is too long.'
    elif not ('a' <= user[0] <= 'z') and not ('A' <= user[0] <= 'Z'):
        session['error'] = 'Username must begin with a letter.'
    elif re.match('\w+', user).end() != len(user):
        session['error'] = 'Username is invalid.'

    if 'error' in session:
        session.save()
        bottle.redirect('/signup')

    try:
        with closing(psycopg2.connect(**connect_kwargs)) as dbconn:
            with closing(dbconn.cursor()) as dbcur:
                dbcur.execute('COMMIT')
                dbcur.execute('CREATE DATABASE "{}"'.format(user))
                dbcur.execute('CREATE ROLE "{}" LOGIN PASSWORD \'{}\''.format(
                    user, password))
                dbcur.execute('ALTER DATABASE "{}" OWNER TO "{}"'.format(
                    user, user))
            dbconn.commit()
    except psycopg2.Error as e:
        if 'already exists' in unicode(e):
            session['error'] = 'Username already exists.'
        else:
            session['error'] = unicode(e)
        session.save()
        bottle.redirect('/signup')

    session = _get_session()
    session['user'] = user
    session['password'] = password
    session.save()
    bottle.redirect('/')


class GeventWebSocketServer(bottle.ServerAdapter):

    def run(self, handler):
        server = gevent.pywsgi.WSGIServer(
            (self.host, self.port), app,
            handler_class=geventwebsocket.handler.WebSocketHandler)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser(
        add_help=False, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '--help', action='help', default=argparse.SUPPRESS,
        help='show this help message and exit')
    parser.add_argument(
        '--version', action='version',
        version='Deco-{}, deco-webui-{}'.format(deco.__version__, __version__))
    if psycopg2.__name__ == 'sqlite3':
        parser.add_argument(
            '-d', dest='database',
            default=os.path.join(tempfile.gettempdir(), 'deco.db'),
            help='database filename')
    else:
        parser.add_argument(
            '-u', dest='user', default=getpass.getuser(),
            help='database username')
        parser.add_argument(
            '-p', dest='password', action='store_true',
            default=argparse.SUPPRESS,
            help='prompt for password')
        parser.add_argument(
            '-h', dest='host', default=argparse.SUPPRESS,
            help='database host address')
        parser.add_argument(
            '-d', dest='database', default=getpass.getuser(),
            help='database name')
    args = vars(parser.parse_args())

    if 'password' in args:
        args['password'] = getpass.getpass()

    global connect_kwargs
    connect_kwargs = args

    # make sure we can connect to the backend database
    try:
        dbconn = psycopg2.connect(**connect_kwargs)
    except psycopg2.Error as e:
        sys.exit(unicode(e))
    else:
        dbconn.close()

    # start the server
    bottle.debug(True)
    bottle.run(app, host='0.0.0.0', port=8080,
               server=GeventWebSocketServer)


if __name__ == '__main__':
    main()
