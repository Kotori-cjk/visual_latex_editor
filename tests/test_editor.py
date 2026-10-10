import base64
import gzip
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from PIL import Image
from pypdf import PdfReader, PdfWriter
from visual_latex_editor import server


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = patch.multiple(server, PROJECT=root, ASSETS=root/'assets',
            SOURCE=root/'report.tex', BUILD=root/'build', TOKEN='test-session',
            STATE={'revision':0,'preview_revision':-1,'busy':False,'pages':[],
                   'log':'','error':'','build_id':'','last_saved':''})
        self.config.start()
        server.initialize()

    def tearDown(self):
        self.config.stop()
        self.temp.cleanup()


class EditorTests(ProjectCase):

    def test_new_document_archives_source_assets_and_clears_preview(self):
        before=server.SOURCE.read_bytes()
        server.STATE.update(build_id='old',pages=[{'number':1}],preview_revision=0)
        server.new_document('新的 50% & 文档')
        archives=list((server.PROJECT/'documents').iterdir())
        self.assertEqual(len(archives),1)
        self.assertEqual((archives[0]/'report.tex').read_bytes(),before)
        self.assertEqual((archives[0]/'assets/tea-cup.png').read_bytes(),(server.ASSETS/'tea-cup.png').read_bytes())
        self.assertIn(r'50\% \&',server.SOURCE.read_text(encoding='utf-8'))
        self.assertEqual(server.STATE['pages'],[])
        self.assertEqual(server.STATE['preview_revision'],-1)

    def test_new_document_rejects_busy_and_invalid_title_without_changes(self):
        before=server.SOURCE.read_bytes()
        server.STATE['busy']=True
        with self.assertRaises(ValueError): server.new_document('title')
        server.STATE['busy']=False
        with self.assertRaises(ValueError): server.new_document(' ')
        self.assertEqual(server.SOURCE.read_bytes(),before)
        self.assertFalse((server.PROJECT/'documents').exists())

    def test_blank_project_initialization_and_restart(self):
        server.SOURCE.unlink()
        server.initialize('blank')
        self.assertNotIn('includegraphics',server.SOURCE.read_text(encoding='utf-8'))
        server.update_source(server.blank_source('My document'))
        server.initialize('blank')
        self.assertIn('My document',server.SOURCE.read_text(encoding='utf-8'))


    def test_restart_restores_valid_preview_even_when_source_has_changed(self):
        folder=server.BUILD/'1791082513300-1'
        folder.mkdir()
        (folder/'report.tex').write_text(server.SOURCE.read_text(encoding='utf-8'),encoding='utf-8')
        pdf=PdfWriter()
        pdf.add_blank_page(width=200,height=300)
        pdf.write(folder/'report.pdf')
        Image.new('RGB',(2,3),'white').save(folder/'page-1.png')
        with gzip.open(folder/'report.synctex.gz','wt') as out:
            out.write('SyncTeX Version:1\nMagnification:1000\nUnit:1\nX Offset:0\nY Offset:0\nContent:\n')
        server.initialize()
        self.assertEqual(server.STATE['build_id'],folder.name)
        self.assertEqual(len(server.STATE['pages']),1)
        self.assertEqual(server.STATE['preview_revision'],0)
        server.update_source(server.SOURCE.read_text(encoding='utf-8').replace(r'\maketitle',r'\invalidCommand'))
        server.initialize()
        self.assertEqual(server.STATE['build_id'],folder.name)
        self.assertEqual(server.STATE['preview_revision'],-1)

    def test_page_settings_round_trip_and_literal_text(self):
        source=server.SOURCE.read_text(encoding='utf-8')
        settings={'header':'custom','footer':'page','header_left':'Tea & 50% {page}'}
        first=server.page_style_source(source,settings)
        self.assertEqual(server.page_settings(first)['header_left'],settings['header_left'])
        self.assertIn(r'\fancyhead[L]{Tea \& 50\% \thepage}',first)
        second=server.page_style_source(first,dict(header='off',footer='off'))
        self.assertEqual(second.count(server.PAGE_BEGIN),1)
        self.assertNotIn(r'\fancyhead[L]',second)
        self.assertNotIn(r'\fancyfoot[C]',second)
        self.assertEqual(source.split(r'\begin{document}',1)[1],second.split(r'\begin{document}',1)[1])

    def test_cleanup_keeps_active_preview_and_unrelated_directory(self):
        for name in ['1791082513300-1','1791082513301-2','1791082513302-3','my-files']:
            folder=server.BUILD/name
            folder.mkdir()
            (folder/'report.pdf').write_bytes(b'cache')
        server.STATE['build_id']='1791082513301-2'
        server.cleanup_builds()
        self.assertEqual({p.name for p in server.BUILD.iterdir()},{'1791082513301-2','my-files'})

    def test_starter_initialization_preserves_existing_edits(self):
        self.assertEqual(server.SOURCE.read_text(encoding='utf-8'), (server.EXAMPLE/'demo.tex').read_text(encoding='utf-8'))
        server.update_source(server.SOURCE.read_text(encoding='utf-8').replace('冷却记录','我的记录',1))
        server.initialize()
        self.assertIn('我的记录',server.SOURCE.read_text(encoding='utf-8'))
        self.assertEqual(len(list(server.ASSETS.glob('*.png'))),2)

    def test_parser_covers_example_and_preserves_inline_math(self):
        source=server.SOURCE.read_text(encoding='utf-8')
        blocks=server.parse_blocks(source)
        self.assertEqual(len([b for b in blocks if b['kind']=='figure']),2)
        self.assertEqual(len([b for b in blocks if b['kind']=='table']),1)
        self.assertEqual(len([b for b in blocks if b['kind']=='math']),1)
        for b in blocks:
            self.assertEqual(source[b['start']:b['end']],b['source'])
            if 'runs' in b:
                self.assertEqual(''.join(r['text'] for r in b['runs']),b['source'])
        runs=server.text_runs('温度 $T(t)=22$，其中 \\textbf{室温} 固定。')
        self.assertTrue(any(r['text']=='$T(t)=22$' and not r['editable'] for r in runs))

    def test_caption_nested_braces(self):
        source=r'\caption{Temperature $\frac{a}{b}$ and \textbf{tea}}'
        span=server.caption_span(source)
        self.assertEqual(source[slice(*span)],r'Temperature $\frac{a}{b}$ and \textbf{tea}')

    def test_image_conversion_flattens_alpha_and_produces_portable_pdf(self):
        data=io.BytesIO()
        Image.new('RGBA',(23,17),(0,0,0,0)).save(data,format='PNG')
        pdf=server.image_pdf(data.getvalue())
        pdf.decode('ascii')
        page=PdfReader(io.BytesIO(pdf)).pages[0]
        self.assertEqual((float(page.mediabox.width),float(page.mediabox.height)),(23,17))
        self.assertEqual(page.images[0].image.convert('RGB').getpixel((5,5)),(255,255,255))

    def test_export_import_round_trip_embeds_both_images(self):
        source=server.SOURCE.read_text(encoding='utf-8')
        exported=server.export_tex().decode('utf-8')
        files=list(server.INLINE.finditer(exported))
        self.assertEqual(len(files),2)
        for item in files:
            self.assertEqual(len(PdfReader(io.BytesIO(item[2].encode('ascii'))).pages),1)
        unpacked=server.unpack_source(exported)
        self.assertEqual(unpacked.split(),source.replace('{tea-cup.png}','{tea-cup-export.pdf}').replace('{cooling-curve.png}','{cooling-curve-export.pdf}').split())

    def test_invalid_import_does_not_overwrite_assets(self):
        asset=server.ASSETS/'existing.pdf'
        asset.write_bytes(b'original')
        bad='\\begin{filecontents*}{existing.pdf}\nreplacement\n\\end{filecontents*}'
        with self.assertRaises(ValueError):
            server.unpack_source(bad)
        self.assertEqual(asset.read_bytes(),b'original')
        traversal='\\begin{filecontents*}{../outside.pdf}\nbytes\n\\end{filecontents*}\n\\begin{document}ok\\end{document}'
        with self.assertRaises(ValueError):
            server.unpack_source(traversal)

    def test_scaled_synctex_image_does_not_cover_neighboring_content(self):
        source='\\begin{document}\n\\begin{figure}[H]\n\\includegraphics{a.pdf}\n\\caption{Tea}\n\\end{figure}\n\\end{document}\n'
        sync='SyncTeX Version:1\nMagnification:1000\nUnit:1\nX Offset:0\nY Offset:0\nContent:\n{1\n(1,4:6553600,13107200:6553600,3932160,0\n(1,3:6553600,13107200:6553600,3932160,0\n(1,3:6553600,13107200:26214400,15728640,0\n)\n)\n)\n}1\n'
        path=server.BUILD/'test.synctex.gz'
        with gzip.open(path,'wt',encoding='utf-8') as out:
            out.write(sync)
        regions=server.sync_regions(path,server.parse_blocks(source),{1:(600,800)})[1]
        self.assertEqual(len(regions),1)
        self.assertLess(regions[0]['w'],.18)
        self.assertLess(regions[0]['h'],.09)

    def test_compiler_failure_keeps_last_successful_preview(self):
        server.STATE.update(build_id='previous',pages=[{'number':1}],preview_revision=0,busy=True)
        result=type('Result',(),{'returncode':1,'stdout':b'! compile error','stderr':b''})()
        with patch.multiple(server, TECTONIC=Path('fake-tectonic'), POPPLER=Path('fake-poppler')):
            with patch.object(server.subprocess,'run',return_value=result):
                server.compile_worker(server.SOURCE.read_text(encoding='utf-8'),1)
        self.assertFalse(server.STATE['busy'])
        self.assertEqual(server.STATE['build_id'],'previous')
        self.assertEqual(server.STATE['pages'],[{'number':1}])
        self.assertIn('compile error',server.STATE['error'])


class HttpTests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.httpd=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.httpd.serve_forever,daemon=True)
        self.thread.start()
        self.url=f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        super().tearDown()

    def request(self,route,data=None,**headers):
        payload=json.dumps(data).encode() if data is not None else None
        headers={'Content-Type':'application/json',**headers}
        return urllib.request.urlopen(urllib.request.Request(self.url+route,payload,headers))

    def test_token_revision_and_image_replacement(self):
        state=json.load(self.request('/api/state'))
        block=next(b for b in state['blocks'] if b['kind']=='figure')
        payload={'revision':0,'id':block['id'],'source':block['source']}
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request('/api/block',payload)
        self.assertEqual(denied.exception.code,403)
        image=io.BytesIO()
        Image.new('RGB',(31,19),'#338855').save(image,format='PNG')
        payload['image']=base64.b64encode(image.getvalue()).decode()
        saved=json.load(self.request('/api/block',payload,**{'X-Editor-Token':'test-session'}))
        self.assertEqual(saved['revision'],1)
        replacement=next(b for b in saved['blocks'] if b['id']==block['id'])
        self.assertTrue(replacement['asset'].startswith('image-'))
        self.assertTrue((server.ASSETS/replacement['asset']).exists())
        with self.assertRaises(urllib.error.HTTPError) as conflict:
            self.request('/api/block',payload,**{'X-Editor-Token':'test-session'})
        self.assertEqual(conflict.exception.code,409)

    def test_local_host_origin_and_static_paths(self):
        self.assertEqual(self.request('/').status,200)
        for route,headers in [('/api/state',{'Host':'untrusted.example'}),('/api/state',{'Origin':'https://untrusted.example'})]:
            with self.assertRaises(urllib.error.HTTPError) as denied:
                self.request(route,**headers)
            self.assertEqual(denied.exception.code,403)
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/assets/../report.tex')


    def test_new_document_requires_current_revision(self):
        state=json.load(self.request('/api/new',{'revision':0,'title':'New'},**{'X-Editor-Token':'test-session'}))
        self.assertIn(r'\title{New}',state['source'])
        with self.assertRaises(urllib.error.HTTPError) as conflict:
            self.request('/api/new',{'revision':0,'title':'Stale'},**{'X-Editor-Token':'test-session'})
        self.assertEqual(conflict.exception.code,409)

    def test_pdf_export_requires_current_build(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/export/pdf')

    def test_page_settings_use_revision_checked_save(self):
        state=json.load(self.request('/api/page-settings',{'revision':0,'settings':{'header':'off','footer':'page'}},**{'X-Editor-Token':'test-session'}))
        self.assertEqual(state['revision'],1)
        self.assertEqual(state['page_settings']['header'],'off')
        self.assertEqual(server.SOURCE.read_text(encoding='utf-8'),state['source'])


if __name__=='__main__':
    unittest.main()
