"""Run the actual compiler/render/edit/export workflow in a disposable project."""
import base64
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from PIL import Image
from pypdf import PdfReader


def main():
    with socket.socket() as available:
        available.bind(('127.0.0.1',0))
        port=available.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory(prefix='visual-latex-check-') as directory:
        root=Path(directory)
        log=(root/'server.log').open('wb')
        process=subprocess.Popen([sys.executable,'-m','visual_latex_editor','--port',str(port),'--project',str(root/'project')],stdout=log,stderr=log)
        def get(route='/api/state'):
            try:
                with urllib.request.urlopen(url+route,timeout=10) as response:
                    return json.load(response) if route=='/api/state' else response.read()
            except urllib.error.HTTPError as exc:
                raise AssertionError(exc.read().decode()) from exc
        def post(route,state,**data):
            request=urllib.request.Request(url+route,json.dumps({'revision':state['revision'],**data}).encode(),
                {'Content-Type':'application/json','X-Editor-Token':state['token']})
            return json.load(urllib.request.urlopen(request,timeout=10))
        def wait():
            deadline=time.time()+300
            while time.time()<deadline:
                if process.poll() is not None:
                    raise AssertionError((root/'server.log').read_text(errors='replace'))
                try:
                    state=get()
                    if not state['busy']:
                        return state
                except (OSError,urllib.error.URLError):
                    pass
                time.sleep(.4)
            raise AssertionError('Timed out waiting for compilation')
        try:
            state=wait()
            assert not state['error'],state['error']
            assert len(state['pages'])==2
            figures=[b for b in state['blocks'] if b['kind']=='figure']
            mapped={r['block_id'] for p in state['pages'] for r in p['regions']}
            assert len(figures)==2 and all(b['id'] in mapped for b in figures)
            print('PASS: two-page example and both clickable images',flush=True)

            saved=post('/api/page-settings',state,settings={'header':'custom','footer':'custom','header_left':'TEA-HEADER','footer_center':'Page {page}'})
            post('/api/compile',saved)
            state=wait()
            assert not state['error'],state['error']
            pdf=PdfReader(io.BytesIO(get('/api/export/pdf')))
            for i,page in enumerate(pdf.pages,1):
                text=page.extract_text()
                assert 'TEA-HEADER' in text and f'Page {i}' in text
            saved=post('/api/page-settings',state,settings={'header':'off','footer':'off'})
            post('/api/compile',saved)
            state=wait()
            assert not state['error'],state['error']
            pdf=PdfReader(io.BytesIO(get('/api/export/pdf')))
            assert all('TEA-HEADER' not in page.extract_text() and 'Page ' not in page.extract_text() for page in pdf.pages)
            print('PASS: editable header/footer and disabling both on every page',flush=True)

            block=next(b for b in state['blocks'] if b['kind']=='text')
            saved=post('/api/block',state,id=block['id'],source=block['source']+' EDITOR-INTEGRATION-MARKER')
            post('/api/compile',saved)
            state=wait()
            assert not state['error'],state['error']
            pdf=PdfReader(io.BytesIO(get('/api/export/pdf')))
            assert 'EDITOR-INTEGRATION-MARKER' in ''.join(p.extract_text() for p in pdf.pages)
            print('PASS: saved text is present in the actual PDF',flush=True)

            picture=io.BytesIO()
            Image.new('RGB',(320,160),'#44aa77').save(picture,format='PNG')
            figure=next(b for b in state['blocks'] if b['kind']=='figure')
            saved=post('/api/block',state,id=figure['id'],source=figure['source'],image=base64.b64encode(picture.getvalue()).decode())
            post('/api/compile',saved)
            state=wait()
            assert not state['error'],state['error']
            pdf=PdfReader(io.BytesIO(get('/api/export/pdf')))
            assert any(image.image.size==(320,160) for page in pdf.pages for image in page.images)
            print('PASS: uploaded replacement image appears in the PDF',flush=True)

            source=state['source']
            previous=state['build_id']
            saved=post('/api/save',state,source=source.replace(r'\maketitle',r'\unknownIntegrationCommand',1))
            post('/api/compile',saved)
            state=wait()
            assert state['error'] and state['build_id']==previous
            assert [p.name for p in (root/'project/build').iterdir() if p.is_dir()]==[previous]
            saved=post('/api/save',state,source=source)
            post('/api/compile',saved)
            state=wait()
            assert not state['error'],state['error']
            print('PASS: real TeX error preserves the last successful preview',flush=True)

            standalone=root/'standalone'
            standalone.mkdir()
            (standalone/'export.tex').write_bytes(get('/api/export/tex'))
            from visual_latex_editor import server
            compiler=server.tool_path(os.environ.get('VISUAL_LATEX_TECTONIC'),'tectonic')
            result=subprocess.run([str(compiler),'export.tex','--outdir','.', '--reruns','1','--untrusted'],cwd=standalone,capture_output=True,timeout=180)
            assert result.returncode==0,(result.stdout+result.stderr).decode(errors='replace')
            assert len(PdfReader(standalone/'export.pdf').pages)==2
            print('PASS: standalone export compiles without external image files',flush=True)
            assert len(list((root/'project/build').iterdir()))==1
            print('PASS: repeated successful and failed builds retain only the current preview',flush=True)
            print('ALL INTEGRATION CHECKS PASSED',flush=True)
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            log.close()


if __name__=='__main__':
    main()
