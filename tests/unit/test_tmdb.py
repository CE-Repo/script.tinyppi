# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""TMDb portraits: title identity, safe matching, bounded requests and fallback."""

import http.client
import io
import urllib.error

import pytest

import xbmcaddon
from web import tmdb
from web.library import details as details_module


@pytest.fixture(autouse=True)
def empty_cache():
    tmdb._CACHE.clear()
    yield
    tmdb._CACHE.clear()


def test_key_and_addon_update(monkeypatch):
    assert tmdb.api_key() == ""
    xbmcaddon.SETTINGS['web_tmdb_key'] = ' secret '
    assert tmdb.api_key() == 'secret'
    def updating():
        raise RuntimeError
    monkeypatch.setattr(tmdb.settings, 'addon', updating)
    assert tmdb.api_key() == ''


def test_requests_authentication_size_and_deadline(monkeypatch):
    calls = []
    data = [b'{"cast": []}', b'[]', b'x' * (tmdb._BIGGEST + 1)]
    def opened(request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(data.pop(0))
    monkeypatch.setattr(tmdb.urllib.request, 'urlopen', opened)
    monkeypatch.setattr(tmdb.time, 'monotonic', lambda: 10)
    assert tmdb._read('movie/1/credits', 'a' * 32, 14) == {'cast': []}
    assert calls[0][0].full_url.endswith('?api_key=' + 'a' * 32)
    assert calls[0][1] == 4
    assert tmdb._read('find/tt1?external_source=imdb_id', 'b' * 32, 14) == {}
    assert '&api_key=' in calls[1][0].full_url
    with pytest.raises(ValueError, match='too large'):
        tmdb._read('movie/1/credits', 'read-token', 14)
    assert calls[2][0].get_header('Authorization') == 'Bearer read-token'
    assert 'read-token' not in calls[2][0].full_url
    with pytest.raises(TimeoutError):
        tmdb._read('movie/1/credits', 'key', 10)


def test_cache_expiry_credential_changes_and_eviction(monkeypatch):
    now = [0]
    calls = []
    def read(path, key, deadline):
        calls.append((path, key))
        return {'cast': []}
    monkeypatch.setattr(tmdb, '_read', read)
    monkeypatch.setattr(tmdb.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(tmdb, '_LIMIT', 2)
    for _ in range(2):
        assert tmdb._get('movie/1/credits', 'key', 4) == {'cast': []}
    assert len(calls) == 1
    tmdb._get('movie/1/credits', 'another-key', 4)
    now[0] = 86401
    tmdb._get('movie/1/credits', 'key', 86405)
    tmdb._get('movie/2/credits', 'key', 86405)
    assert len(calls) == 4 and len(tmdb._CACHE) == 2
    assert ('another-key', 'movie/1/credits') not in tmdb._CACHE


@pytest.mark.parametrize('error', [OSError(), ValueError(), http.client.HTTPException(),
                                   urllib.error.HTTPError('url', 429, 'limit', {}, None)])
def test_failures_are_negative_cached(monkeypatch, error):
    calls = []
    def read(*args):
        calls.append(args)
        raise error
    monkeypatch.setattr(tmdb, '_read', read)
    monkeypatch.setattr(tmdb.time, 'monotonic', lambda: 0)
    assert tmdb._get('movie/1/credits', 'key', 4) == {}
    assert tmdb._get('movie/1/credits', 'key', 4) == {}
    assert len(calls) == 1
    assert next(iter(tmdb._CACHE.values()))[0] == 300


@pytest.mark.parametrize(('value', 'expected'), [('12', 12), (12, 12), ('0', None),
    (None, None), (True, None), (-1, None), ('12/credits', None), ('1.0', None)])
def test_ids(value, expected):
    assert tmdb._ident(value) == expected


def test_title_identity_and_imdb_fallback(monkeypatch):
    answers = [{'movie_results': [{'id': 9}]}, {'tv_results': [{'id': 8}]},
               {'movie_results': []}, {'movie_results': [1]},
               {'movie_results': [{'id': 1}, {'id': 2}]}, {}]
    paths = []
    def get(path, key, deadline):
        paths.append(path)
        return answers.pop(0)
    monkeypatch.setattr(tmdb, '_get', get)
    assert tmdb._title_id({}, 'movie', 'key', 4) is None
    assert tmdb._title_id({'uniqueid': {}}, 'movie', 'key', 4) is None
    assert tmdb._title_id({'uniqueid': {'tmdb': '42'}}, 'movie', 'key', 4) == 42
    for kind, expected in [('movie', 9), ('tvshow', 8), ('movie', None),
                           ('movie', None), ('movie', None), ('movie', None)]:
        assert tmdb._title_id({'uniqueid': {'imdb': 'tt123'}}, kind, 'key', 4) == expected
    assert paths == ['find/tt123?external_source=imdb_id'] * 6


def test_movie_show_and_episode_paths(monkeypatch):
    paths = []
    monkeypatch.setattr(tmdb, '_get', lambda path, *args: paths.append(path) or {'cast': []})
    monkeypatch.setattr(tmdb.common, 'rpc', lambda *args: {'result': {'tvshowdetails': {'uniqueid': {'tmdb': '99'}}}})
    for kind, row in [('movie', {'uniqueid': {'tmdb': '1'}}),
                      ('tvshow', {'uniqueid': {'tmdb': '2'}}),
                      ('episode', {'tvshowid': 3, 'season': 0, 'episode': 1})]:
        assert tmdb.credits(kind, row, 'key') == {'cast': []}
    assert paths == ['movie/1/credits', 'tv/2/credits', 'tv/99/season/0/episode/1/credits']
    assert tmdb.credits('episode', {}, 'key') == {}
    assert tmdb.credits('episode', {'tvshowid': 3}, 'key') == {}
    assert tmdb.credits('episode', {'tvshowid': 3, 'season': 1}, 'key') == {}
    assert tmdb.credits('movie', {}, 'key') == {}
    for answer in [{}, {'result': 'bad'}, {'result': {'tvshowdetails': 'bad'}}]:
        monkeypatch.setattr(tmdb.common, 'rpc', lambda *args, answer=answer: answer)
        assert tmdb.credits('episode', {'tvshowid': 3}, 'key') == {}


def test_role_matching_safe_paths_and_ambiguous_names():
    def person(name='Denis', path='/portrait.jpg', **extra):
        return {'name': name, 'profile_path': path, **extra}
    answer = {'crew': [person(job='Director'), person(job='Director'),
        person('Writer', '/writer.png', department='Writing'),
        person('Other', job='Camera'), person('', job='Director'),
        person('No image', '', job='Director'), person('Unsafe', '//host/a.jpg', job='Director'),
        person('Duplicate', '/a.jpg', job='Director'), person('Duplicate', '/b.jpg', job='Director'), None]}
    assert tmdb.portraits(answer, 'crew', 'director') == {'denis': 'https://image.tmdb.org/t/p/w185/portrait.jpg'}
    assert tmdb.portraits(answer, 'crew', 'writer') == {'writer': 'https://image.tmdb.org/t/p/w185/writer.png'}
    assert tmdb.portraits({'cast': [person()]}, 'cast') == {'denis': 'https://image.tmdb.org/t/p/w185/portrait.jpg'}
    assert tmdb.portraits({}, 'cast') == {}
    assert tmdb.portraits({'cast': 'bad'}, 'cast') == {}


def test_enrichment_preserves_kodi_data_and_registers_only_missing_portraits(monkeypatch):
    monkeypatch.setattr(tmdb, 'api_key', lambda: 'key')
    calls = []
    answer = {'cast': [{'name': 'Actor', 'profile_path': '/actor.jpg'},
                       {'name': 'Already', 'profile_path': '/replace.jpg'}],
              'guest_stars': [{'name': 'Guest', 'profile_path': '/guest.jpg'}],
              'crew': [{'name': 'Director', 'job': 'Director', 'profile_path': '/director.jpg'},
                       {'name': 'Writer', 'department': 'Writing', 'profile_path': '/writer.jpg'}]}
    monkeypatch.setattr(tmdb, 'credits', lambda *args: calls.append(args) or answer)
    found = {'directors': ['Director', 'Unknown'], 'writers': ['Writer'], 'cast': [
        {'name': ' ACTOR ', 'role': 'Hero'}, {'name': 'Already', 'role': '', 'thumbnail': 'kodi'},
        {'name': 'Guest', 'role': 'Guest'}, {'name': 'Unknown', 'role': ''}]}
    details_module._missing_portraits(found, {}, 'movie')
    assert len(calls) == 1
    assert found['cast'][1]['thumbnail'] == 'kodi'
    assert found['cast'][0]['role'] == 'Hero' and found['cast'][0]['name'] == ' ACTOR '
    for person, image in [(found['cast'][0], 'actor'), (found['cast'][2], 'guest'),
                          (found['crew'][0], 'director'), (found['crew'][2], 'writer')]:
        assert details_module.portrait_path(person['thumbnail']) == f'https://image.tmdb.org/t/p/w185/{image}.jpg'
    assert found['crew'][1] == {'name': 'Unknown', 'role': 'director'}
    for data in [{}, {'cast': [{'name': 'Already', 'role': '', 'thumbnail': 'kodi'}]}]:
        details_module._missing_portraits(data, {}, 'movie')
    assert len(calls) == 1
    cast_only = {'cast': [{'name': 'Unknown', 'role': ''}]}
    details_module._missing_portraits(cast_only, {}, 'movie')
    assert len(calls) == 2 and 'crew' not in cast_only
