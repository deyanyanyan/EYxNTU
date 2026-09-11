"""Exercise a running Docker stack. No host dependencies or model downloads by default.

docker compose ... exec -T api python /srv/scripts/smoke.py [--ingest] [--llm]
Only the disposable project created by this script is deleted afterwards.
"""
import argparse
import io
import json
import time
import uuid

import httpx

from app.config import settings


def main():
    args_parser = argparse.ArgumentParser()
    args_parser.add_argument('--ingest', action='store_true', help='test PDF, DOCX, PPTX and TXT ingestion and retrieval; requires model caches')
    args_parser.add_argument('--llm', action='store_true', help='check local chat and structured output; requires a pulled LLM')
    restart = args_parser.add_mutually_exclusive_group()
    restart.add_argument('--save-restart', action='store_true', help='leave a disposable project and checkpoint for restart verification')
    restart.add_argument('--verify-restart', action='store_true', help='verify and remove the saved disposable project after restart')
    args = args_parser.parse_args()
    checkpoint = settings.artifacts_dir / 'smoke-restart.json'
    if args.save_restart and checkpoint.exists():
        raise RuntimeError('A restart checkpoint already exists. Run --verify-restart before preparing another.')
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=300) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else None

        assert request('GET', '/health')['db'] is True
        web = httpx.get('http://web:3000/login', timeout=30)
        web.raise_for_status()
        assert 'Sign in' in web.text
        token = request('POST', '/auth/token', data={
            'username': settings.default_admin_email, 'password': settings.default_admin_password,
        })
        client.headers['Authorization'] = 'Bearer ' + token['access_token']
        assert request('GET', '/auth/me')['role'] == 'admin'
        if args.verify_restart:
            saved = json.loads(checkpoint.read_text())
            path = '/projects/' + saved['id']
            persisted = request('GET', path)
            assert persisted['name'] == saved['name'] and persisted['target_audience'] == 'New lab members'
            request('DELETE', path)
            checkpoint.unlink()
            print('PASS: user login and saved project survived restart; disposable project removed')
        project = request('POST', '/projects', json={'name': 'Smoke ' + uuid.uuid4().hex[:8], 'learning_goals': 'Understand the lab rules'})
        project_path = '/projects/' + project['id']
        preserve = False
        try:
            assert request('GET', project_path)['id'] == project['id']
            assert request('PATCH', project_path, json={'target_audience': 'New lab members'})['target_audience'] == 'New lab members'
            assert request('GET', '/jobs') is not None
            if args.ingest:
                check_ingest(request, project_path)
            print('PASS: web, database, login, current user, project create/read/update, jobs')
            if args.save_restart:
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                checkpoint.write_text(json.dumps({'id': project['id'], 'name': project['name']}))
                preserve = True
                print('Prepared disposable project for --verify-restart')
        finally:
            if not preserve:
                request('DELETE', project_path)
    if args.llm:
        import asyncio
        from pydantic import BaseModel
        from app.core.llm.client import chat_structured

        class Answer(BaseModel):
            message: str

        result = asyncio.run(chat_structured('Follow the requested JSON schema.', 'Return a short greeting in message.', Answer))
        assert result.message
        print('PASS: local LLM structured output')


def check_ingest(request, project_path):
    from docx import Document
    from pptx import Presentation

    passage = 'The training lab requires eye protection when operating the lathe. Equipment inspections take place every 30 days. Report defects to the lab supervisor before using equipment.'
    doc = Document()
    doc.add_heading('Lab safety', 1)
    doc.add_paragraph(passage)
    doc_bytes = io.BytesIO()
    doc.save(doc_bytes)
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = 'Lab safety'
    slide.placeholders[1].text = passage
    deck_bytes = io.BytesIO()
    deck.save(deck_bytes)
    # Minimal real PDF; avoids introducing a PDF-generation dependency for a smoke check.
    stream = ('BT /F1 12 Tf 50 750 Td (Lab safety) Tj 0 -25 Td '
              '(Wear eye protection when operating the lathe.) Tj 0 -25 Td '
              '(Equipment inspections take place every 30 days.) Tj ET').encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    pdf = b'%PDF-1.4\n'
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(pdf)
    pdf += b'xref\n0 6\n0000000000 65535 f \n'
    pdf += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    pdf += f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    fixtures = [('lab.txt', passage.encode()), ('lab.docx', doc_bytes.getvalue()), ('lab.pptx', deck_bytes.getvalue()), ('lab.pdf', pdf)]
    sources = []
    try:
        for filename, content in fixtures:
            source = request('POST', project_path + '/sources', files={'file': (filename, content)})
            sources.append(source['id'])
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                current = next(s for s in request('GET', project_path + '/sources') if s['id'] == source['id'])
                if current['status'] == 'failed':
                    raise RuntimeError(f'{filename} ingestion failed: {current["error"]}')
                if current['status'] == 'ready':
                    assert current['chunk_count'] > 0
                    break
                time.sleep(2)
            else:
                raise TimeoutError(f'{filename} did not become ready within 15 minutes')
            hits = request('POST', project_path + '/search', json={
                'query': 'How often is equipment inspected?', 'threshold': 0, 'source_ids': [source['id']],
            })
            assert hits and any('30 days' in hit['text'] for hit in hits)
            assert all(hit['source_id'] == source['id'] and hit['chunk_id'] for hit in hits)
            print(f'PASS: {filename} upload, worker ingestion, embeddings, source-scoped retrieval')
    finally:
        for source_id in sources:
            request('DELETE', project_path + '/sources/' + source_id)


if __name__ == '__main__':
    main()
