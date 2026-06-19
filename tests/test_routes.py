import json


def test_index_route(test_client):
    resp = test_client.get('/')
    assert resp.status_code == 200

def test_open_missing_file(test_client):
    resp = test_client.post('/api/open', json={"path": "/nonexistent/file.pdf"})
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data

def test_get_page_no_doc(test_client):
    resp = test_client.get('/api/page/left/0')
    assert resp.status_code in (400, 404)
    data = json.loads(resp.data)
    assert "error" in data

def test_page_count_no_doc(test_client):
    resp = test_client.get('/api/page-count/left')
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data

def test_translate_no_doc(test_client):
    resp = test_client.post('/api/translate/0')
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data

def test_translated_pages_no_doc(test_client):
    resp = test_client.get('/api/translated-pages')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data == {"pages": []}
