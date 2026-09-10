"""Real login + PostgreSQL isolation tests, no authentication bypass."""
import time
import uuid

from sqlalchemy import select
from app.auth import hash_password, token_hash
from app.db import User, LoginSession, Document, get_session_factory
from test_api import client


def second_account(client):
    name = uuid.uuid4().hex
    async def provision():
        async with get_session_factory()() as session:
            session.add(User(id=name, username=name, password_hash=hash_password('another-password')))
            await session.commit()
    client.portal.call(provision)
    response = client.post('/auth/login', json={'username': name, 'password': 'another-password'})
    assert response.status_code == 200
    return response.json()['access_token']


def test_login_logout_expiry_and_disabled_account(client):
    first = client.headers.pop('Authorization')
    for method, path in [('GET', '/history'), ('GET', '/documents'), ('POST', '/chat'),
                         ('POST', '/chat/stream'), ('POST', '/agent'), ('POST', '/agent/stream'),
                         ('GET', '/mcp/tools'), ('GET', '/auth/me')]:
        assert client.request(method, path).status_code == 401
    assert client.get('/health').status_code == 200
    assert 'rag' not in client.get('/health').json()
    assert client.post('/auth/login', json={'username':'missing', 'password':'wrong'}).status_code == 401
    client.headers['Authorization'] = 'Bearer forged'
    assert client.get('/history').status_code == 401
    token = second_account(client)
    client.headers['Authorization'] = 'Bearer ' + token
    assert client.get('/auth/me').status_code == 200
    assert client.post('/auth/logout').status_code == 200
    assert client.get('/auth/me').status_code == 401
    token = second_account(client)
    async def expire():
        async with get_session_factory()() as session:
            item = await session.get(LoginSession, token_hash(token))
            item.expires_at = time.time() - 1
            await session.commit()
    client.portal.call(expire)
    client.headers['Authorization'] = 'Bearer ' + token
    assert client.get('/history').status_code == 401
    client.headers['Authorization'] = first
    user_id = client.get('/auth/me').json()['id']
    async def disable():
        async with get_session_factory()() as session:
            user = await session.get(User, user_id)
            user.active = False
            await session.commit()
    client.portal.call(disable)
    assert client.get('/history').status_code == 401


def test_cross_user_history_documents_rag_agent_and_stream(client):
    first = client.headers['Authorization']
    doc = client.post('/documents/upload', files={'file': ('private.md', '年假秘密条款：员工年假为987天。'.encode(), 'text/markdown')}).json()
    conv = client.post('/chat', json={'message': '我的私有消息'}).json()['conversation_id']
    second = second_account(client)
    client.headers['Authorization'] = 'Bearer ' + second
    assert client.get('/history').json()['conversations'] == []
    assert client.get('/documents').json()['documents'] == []
    assert client.get(f'/history/{conv}').status_code == 404
    assert client.delete(f'/history/{conv}').status_code == 404
    assert client.post(f'/history/{conv}/truncate', json={'keep_messages':0}).status_code == 404
    assert client.delete(f"/documents/{doc['id']}").status_code == 404
    for path in ['/chat', '/chat/stream', '/agent', '/agent/stream']:
        assert client.post(path, json={'message':'年假', 'conversation_id':conv}).status_code == 404
    assert client.post('/documents/search', json={'query':'年假'}).json()['hits'] == []
    assert client.post('/chat', json={'message':'年假', 'use_rag':True}).json()['sources'] == []
    for path in ['/agent', '/agent/stream', '/chat/stream']:
        response = client.post(path, json={'message':'年假', 'use_rag':True})
        assert response.status_code == 200
        assert '987' not in response.text
    for path in ['/agent', '/agent/stream']:
        assert client.post(path, json={'message':'年假', 'use_mcp':True}).status_code == 403
    assert client.get('/mcp/tools').status_code == 403
    own = client.post('/chat/stream', json={'message':'B的消息'})
    assert own.status_code == 200
    b_history = client.get('/history').json()['conversations']
    assert b_history
    client.headers['Authorization'] = first
    a_history = client.get('/history').json()['conversations']
    assert [item['id'] for item in a_history] == [conv]
    for item in b_history:
        assert client.get('/history/' + item['id']).status_code == 404
    assert client.get(f'/history/{conv}').json()['messages'][0]['content'] == '我的私有消息'
    assert client.post('/documents/search', json={'query':'年假'}).json()['hits'][0]['document_id'] == doc['id']
    client.delete(f"/documents/{doc['id']}")


def test_legacy_unowned_documents_hidden(client):
    async def provision():
        async with get_session_factory()() as session:
            doc = Document(title='legacy', source='legacy', created_at=time.time())
            session.add(doc)
            await session.commit()
            return doc.id
    doc_id = client.portal.call(provision)
    assert all(d['id'] != doc_id for d in client.get('/documents').json()['documents'])
    assert client.delete(f'/documents/{doc_id}').status_code == 404
