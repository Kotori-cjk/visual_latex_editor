"""Local visual LaTeX editor: source-backed edits and actual PDF previews."""
from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.errors import PdfReadError

APP = Path(__file__).resolve().parent
PROJECT = Path.cwd() / '.visual_latex_editor'
ASSETS = PROJECT / 'assets'
SOURCE = PROJECT / 'report.tex'
BUILD = PROJECT / 'build'
EXAMPLE = APP / 'example'
TECTONIC = None
POPPLER = None
CACHE = None
TOKEN = secrets.token_urlsafe(24)
LOCK = threading.RLock()
STATE = {'revision': 0, 'preview_revision': -1, 'busy': False, 'pages': [],
         'log': '', 'error': '', 'build_id': '', 'last_saved': ''}
INLINE = re.compile(r'\\begin\{filecontents\*\}(?:\[[^\]]*\])?\{([^}]+)\}\s*\n(.*?)\\end\{filecontents\*\}', re.S)


def atomic_text(path, text):
    temp = path.with_suffix(path.suffix + '.new')
    temp.write_text(text, encoding='utf-8')
    os.replace(temp, path)


def unpack_source(source):
    """Keep the working source small; recover embedded assets without changing them."""
    extracted = {}
    def asset(match):
        name = match[1]
        if Path(name).name != name or not re.fullmatch(r'[\w.\-]+', name):
            raise ValueError('嵌入图片的文件名不受支持。请使用不含目录的文件名。')
        extracted[name] = match[2].encode('ascii')
        return ''
    source = INLINE.sub(asset, source)
    if r'\begin{document}' not in source or r'\end{document}' not in source:
        raise ValueError('请选择完整的 LaTeX 文档（包含 document 环境）。')
    parse_blocks(source)
    for name, data in extracted.items():
        (ASSETS/name).write_bytes(data)
    return source



def blank_source(title='未命名文档'):
    if not isinstance(title, str) or not title.strip() or len(title)>200:
        raise ValueError('请输入 1–200 字的文档标题。')
    escapes = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
               '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}',
               '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    title=''.join(escapes.get(c,c) for c in ' '.join(title.split()))
    return '\n'.join([r'\documentclass[UTF8,a4paper,11pt,fontset='+('windows' if os.name == 'nt' else 'fandol')+']{ctexart}',
        r'\usepackage[margin=2.4cm]{geometry}',
        r'\usepackage{amsmath,booktabs,graphicx,float,caption,hyperref}',
        r'\hypersetup{hidelinks}',r'\title{'+title+'}',r'\author{}',r'\date{}',
        r'\begin{document}',r'\maketitle','','从这里开始写作。','',r'\end{document}',''])


def new_document(title):
    if STATE['busy']:
        raise ValueError('请等待编译结束后再新建文档。')
    source=blank_source(title)
    archive=PROJECT/'documents'/(time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3))
    archive.mkdir(parents=True)
    shutil.copy2(SOURCE, archive/'report.tex')
    shutil.copytree(ASSETS, archive/'assets')
    update_source(source)
    STATE.update(pages=[],build_id='',preview_revision=-1,error='',log='')


def initialize(template="example"):
    ASSETS.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists():
        atomic_text(SOURCE, blank_source() if template == 'blank' else (EXAMPLE/'demo.tex').read_text(encoding='utf-8'))
        for image in (EXAMPLE/'assets').iterdir():
            if image.is_file():
                shutil.copy2(image, ASSETS/image.name)
    STATE['last_saved'] = time.strftime('%H:%M:%S')
    restore_preview()


def image_pdf(data):
    """ASCII-only image PDF, so the downloaded .tex can embed every replacement."""
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGBA')
    bg = Image.new('RGB', im.size, 'white')
    bg.paste(im, mask=im.getchannel('A'))
    jpeg = io.BytesIO()
    bg.save(jpeg, format='JPEG', quality=95, subsampling=0)
    encoded = jpeg.getvalue().hex()
    hexdata = '\n'.join(encoded[i:i+100] for i in range(0, len(encoded), 100)) + '>\n'
    w, h = bg.size
    paint = f'q {w} 0 0 {h} 0 0 cm /Im0 Do Q\n'
    objs = ['<< /Type /Catalog /Pages 2 0 R >>',
            '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>',
            f'<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter [/ASCIIHexDecode /DCTDecode] /Length {len(hexdata)} >>\nstream\n{hexdata}endstream',
            f'<< /Length {len(paint)} >>\nstream\n{paint}endstream']
    pdf = '%PDF-1.4\n'
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(pdf))
        pdf += f'{i} 0 obj\n{obj}\nendobj\n'
    start = len(pdf)
    pdf += 'xref\n0 6\n0000000000 65535 f \n'
    pdf += ''.join(f'{x:010d} 00000 n \n' for x in offsets)
    pdf += f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'
    return pdf.encode('ascii')


def balanced_argument(text, start):
    depth = 0
    for i in range(start, len(text)):
        if text[i] in '{}':
            slashes = len(text[:i]) - len(text[:i].rstrip('\\'))
            if slashes % 2:
                continue
            depth += 1 if text[i] == '{' else -1
            if depth == 0:
                return (start+1, i)
    raise ValueError('花括号不匹配，请在 LaTeX 模式中检查。')


def caption_span(text):
    m = re.search(r'\\caption(?:\[[^\]]*\])?\s*\{', text)
    return balanced_argument(text, m.end()-1) if m else None


def text_runs(text):
    """Expose prose for plain-text edits while keeping formulas and TeX syntax intact."""
    protected = re.compile(r'(?s)(?<!\\)\$\$.*?(?<!\\)\$\$|(?<!\\)\$.*?(?<!\\)\$|\\\(.*?\\\)|\\[a-zA-Z@]+\*?|\\.|[{}&~^_]')
    out, pos = [], 0
    for m in protected.finditer(text):
        if m.start() > pos:
            out.append({'text': text[pos:m.start()], 'editable': True})
        out.append({'text': m[0], 'editable': False})
        pos = m.end()
    if pos < len(text):
        out.append({'text': text[pos:], 'editable': True})
    return out


def parse_blocks(source):
    lines = source.splitlines(keepends=True)
    offsets, total = [], 0
    for line in lines:
        offsets.append(total)
        total += len(line)
    blocks = []
    def add(start, end, kind):
        a, b = offsets[start], offsets[end] if end < len(lines) else len(source)
        raw = source[a:b].rstrip('\r\n')
        b = a + len(raw)
        label = re.sub(r'\\[a-zA-Z]+\*?|[{}$\\]', '', raw).strip().replace('\n', ' ')
        block = {'id': f'b{len(blocks)}', 'start': a, 'end': b, 'line_start': start+1,
                 'line_end': end, 'kind': kind, 'source': raw, 'label': label[:70]}
        if kind in ('text', 'heading', 'title'):
            block['runs'] = text_runs(raw)
        if kind == 'figure':
            m = re.search(r'\\includegraphics(?:\[([^\]]*)\])?\{([^}]+)\}', raw)
            span = caption_span(raw)
            block.update(asset=m[2] if m else '', options=m[1] or '' if m else '',
                         caption=raw[slice(*span)] if span else '')
            block['label'] = block['caption'] or block['asset'] or '图片'
        blocks.append(block)
    # Document title is defined in the preamble, but shown on page 1.
    for i, line in enumerate(lines):
        if re.match(r'\s*\\title\{', line):
            add(i, i+1, 'title')
    i = next(j+1 for j, line in enumerate(lines) if r'\begin{document}' in line)
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == r'\end{document}':
            break
        if not stripped or stripped.startswith('%') or re.fullmatch(r'\\(?:clearpage|newpage|maketitle|vspace\{[^}]*\})', stripped):
            i += 1
            continue
        if re.match(r'\\(?:section|subsection|subsubsection|paragraph)\*?\{', stripped):
            add(i, i+1, 'heading'); i += 1; continue
        if stripped.startswith(r'\['):
            j = i+1
            while j < len(lines) and r'\]' not in lines[j-1]:
                j += 1
            add(i, j, 'math'); i = j; continue
        env = re.match(r'\\begin\{([^}]+)\}', stripped)
        if env:
            name, depth, j = env[1], 0, i
            while j < len(lines):
                depth += lines[j].count(r'\begin{' + name + '}')
                depth -= lines[j].count(r'\end{' + name + '}')
                j += 1
                if depth <= 0:
                    break
            kind = 'figure' if name == 'figure' else 'table' if 'tabular' in ''.join(lines[i:j]) else 'latex'
            add(i, j, kind); i = j; continue
        j = i+1
        while j < len(lines):
            t = lines[j].strip()
            if not t or re.match(r'\\(?:begin|end|section|subsection|subsubsection|paragraph|clearpage|newpage|\[)', t):
                break
            j += 1
        add(i, j, 'text'); i = j
    return blocks


def sync_regions(sync_path, blocks, dimensions):
    """Read emitted SyncTeX boxes; PDF coordinates have their origin at top left."""
    data = gzip.open(sync_path, 'rt', encoding='utf-8', errors='replace').read()
    unit = float(re.search(r'^Unit:(\d+)', data, re.M)[1])
    mag = float(re.search(r'^Magnification:(\d+)', data, re.M)[1]) / 1000
    factor = unit * mag / 65536 * 72 / 72.27
    offsets = [float(re.search(r'^'+axis+r' Offset:(-?\d+)', data, re.M)[1]) * factor for axis in ('X','Y')]
    owner = {line: block for block in blocks for line in range(block['line_start'], block['line_end']+1)}
    title = next((b for b in blocks if b['kind'] == 'title'), None)
    figure_lines = {}
    for block in blocks:
        if block['kind'] == 'figure':
            figure_lines[block['id']] = {block['line_start']+i for i,line in enumerate(block['source'].splitlines())
                                       if '\\includegraphics' in line or '\\caption' in line}
    rects = {}
    stack = []
    page = 0
    pattern = re.compile(r'^([\[(hv])([0-9]+),(\d+):(-?\d+),(-?\d+):(-?\d+),(-?\d+),(-?\d+)')
    leaves = re.compile(r'^[xgk\$]([0-9]+),(\d+):')
    def record(block, box):
        if not block or page not in dimensions:
            return
        x, y, w, h, d = box
        if w <= 0 or h+d <= 0:
            return
        pw, ph = dimensions[page]
        if w > pw or h+d > ph*.90:
            return
        key = (block['id'], page)
        rects.setdefault(key, []).append((max(0,x-1), max(0,y-h-2), min(pw,x+w+1), min(ph,y+d+2)))
    for line in data.splitlines():
        if re.fullmatch(r'\{\d+', line):
            page = int(line[1:]); stack = []; continue
        if line in (']', ')'):
            if stack:
                stack.pop()
            continue
        m = pattern.match(line)
        if m:
            typ, tag, n = m[1], int(m[2]), int(m[3])
            x,y,w,h,d = [int(m[i])*factor for i in range(4,9)]
            box = (x+offsets[0], y+offsets[1], w,h,d)
            parent = next((b for t,b in reversed(stack) if t=='(' and b[2]>2 and b[3]+b[4]>2),None)
            # XeTeX emits both scaled image boxes and an unscaled inner image box.
            # Keep the visible scaled geometry; the inner box can cover unrelated text.
            fits_parent = not parent or (w<=parent[2]+1 and h+d<=parent[3]+parent[4]+1)
            if typ in ('[','('):
                stack.append((typ, box))
            block = owner.get(n) if tag == 1 else None
            if typ in ('(', 'h') and block and fits_parent:
                if block['kind']=='figure' and n in figure_lines[block['id']]:
                    record(block,box)
                elif block['kind'] not in ('figure','text') and n>block['line_start']:
                    record(block,box)
                elif block['kind'] in ('heading','title'):
                    record(block,box)
            # TeX reports the title's lines at the command after maketitle.
            if page == 1 and title and typ == '(' and y < 125 and w > 100 and h > 5:
                record(title, box)
        else:
            m = leaves.match(line)
            if m and int(m[1]) == 1:
                block = owner.get(int(m[2]))
                box = next((box for typ,box in reversed(stack) if typ=='(' and box[2]>2 and box[3]+box[4]>2), None)
                if box and block and block['kind'] != 'figure' and box[3]+box[4] < 60 and not (block['kind']=='math' and int(m[2])==block['line_start']):
                    record(block, box)
    regions = {page: [] for page in dimensions}
    for (bid,page), items in rects.items():
        # Merge overlapping / adjacent line boxes, but keep spans on different pages separate.
        unique = sorted(set(items), key=lambda r:(r[1],r[0]))
        merged = []
        for r in unique:
            if merged and r[1] <= merged[-1][3]+4:
                a = merged[-1]
                merged[-1] = (min(a[0],r[0]),min(a[1],r[1]),max(a[2],r[2]),max(a[3],r[3]))
            else:
                merged.append(r)
        pw,ph = dimensions[page]
        for x1,y1,x2,y2 in merged:
            regions[page].append({'block_id':bid,'x':x1/pw,'y':y1/ph,'w':(x2-x1)/pw,'h':(y2-y1)/ph})
    return regions



PAGE_BEGIN = '% BEGIN VLE PAGE STYLE'
PAGE_END = '% END VLE PAGE STYLE'


def page_settings(source):
    match = re.search(r'^% VLE SETTINGS (.+)$', source, re.M)
    if match:
        return json.loads(match[1])
    plain = bool(re.search(r'\\pagestyle\{plain\}', source))
    empty = bool(re.search(r'\\pagestyle\{empty\}', source))
    return {'header': 'off' if plain or empty else 'auto',
            'footer': 'off' if empty else 'page',
            'header_left': '', 'header_center': '', 'header_right': '',
            'footer_left': '', 'footer_center': '', 'footer_right': ''}


def page_style_source(source, settings):
    if settings.get('header') not in ('off', 'auto', 'custom') or settings.get('footer') not in ('off', 'page', 'custom'):
        raise ValueError('Invalid header/footer mode')
    values = {'header': settings['header'], 'footer': settings['footer']}
    for area in ('header', 'footer'):
        for slot in ('left', 'center', 'right'):
            key = area + '_' + slot
            value = settings.get(key, '')
            if not isinstance(value, str) or len(value) > 200 or '\n' in value or '\r' in value:
                raise ValueError('Header/footer text must be a single line of at most 200 characters')
            values[key] = value
    def tex(text):
        escapes = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
                   '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
        return r'\thepage'.join(''.join(escapes.get(c, c) for c in part) for part in text.split('{page}'))
    commands = [r'\fancyhf{}', r'\renewcommand{\headrulewidth}{0pt}', r'\renewcommand{\footrulewidth}{0pt}']
    for area, command in [('header', 'fancyhead'), ('footer', 'fancyfoot')]:
        if values[area] == 'custom':
            for slot, position in [('left', 'L'), ('center', 'C'), ('right', 'R')]:
                commands.append('\\' + command + '[' + position + ']{' + tex(values[area+'_'+slot]) + '}')
        elif values[area] == 'auto':
            commands.append(r'\fancyhead[L]{\nouppercase{\leftmark}}')
        elif values[area] == 'page':
            commands.append(r'\fancyfoot[C]{\thepage}')
    source = re.sub(re.escape(PAGE_BEGIN) + r'.*?' + re.escape(PAGE_END) + r'\n?', '', source, flags=re.S)
    package = '' if re.search(r'\\usepackage(?:\[[^\]]*\])?\{[^}]*\bfancyhdr\b', source) else '\\usepackage{fancyhdr}\n'
    body = '\n'.join(commands)
    block = '\n'.join([PAGE_BEGIN, '% VLE SETTINGS '+json.dumps(values, ensure_ascii=True),
                       package.rstrip(), r'\setlength{\headheight}{16pt}',
                       r'\fancypagestyle{vle}{'+body+'}', r'\fancypagestyle{plain}{'+body+'}',
                       r'\pagestyle{vle}', PAGE_END, ''])
    return source.replace(r'\begin{document}', block+r'\begin{document}', 1)



def cached_preview(folder, source):
    pdf = PdfReader(folder/'report.pdf')
    dims = {i+1:(float(p.mediabox.width),float(p.mediabox.height)) for i,p in enumerate(pdf.pages)}
    regions = sync_regions(folder/'report.synctex.gz', parse_blocks(source), dims)
    pages = []
    for i,(w,h) in dims.items():
        png = next(p for p in folder.glob('page-*.png') if int(p.stem.split('-')[-1])==i)
        pages.append({'number':i,'width':w,'height':h,'image':f'/build/{folder.name}/{png.name}', 'regions':regions[i]})
    return pages


def restore_preview():
    for folder in sorted(BUILD.iterdir(), reverse=True):
        if not folder.is_dir() or folder.is_symlink() or not re.fullmatch(r'\d{13}-\d+', folder.name):
            continue
        try:
            source = (folder/'report.tex').read_text(encoding='utf-8')
            pages = cached_preview(folder, source)
        except (OSError, ValueError, StopIteration, PdfReadError):
            continue
        STATE.update(pages=pages, build_id=folder.name,
                     preview_revision=STATE['revision'] if source==SOURCE.read_text(encoding='utf-8') else -1)
        break


def cleanup_builds():
    """Only remove managed compilation caches, never user documents/assets."""
    root = BUILD.resolve()
    folders = [p for p in BUILD.iterdir() if p.is_dir() and not p.is_symlink() and re.fullmatch(r'\d{13}-\d+', p.name)]
    keep = STATE['build_id']
    if not keep:
        valid = [p for p in folders if (p/'report.pdf').is_file() and list(p.glob('page-*.png'))]
        keep = max((p.name for p in valid), default='')
    for folder in folders:
        if folder.name != keep and folder.resolve().parent == root:
            shutil.rmtree(folder)


def public_state():
    with LOCK:
        source = SOURCE.read_text(encoding='utf-8')
        return {**STATE, 'blocks': parse_blocks(source), 'source': source,
                'project': str(SOURCE), 'token': TOKEN, 'page_settings': page_settings(source)}


def compile_worker(source, revision):
    name = f'{int(time.time()*1000)}-{revision}'
    folder = BUILD / name
    try:
        folder.mkdir()
        atomic_text(folder / 'report.tex', source)
        for asset_name in set(re.findall(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}', source)):
            asset = (ASSETS/asset_name).resolve()
            if asset.parent != ASSETS.resolve() or not asset.is_file():
                raise ValueError('Missing or invalid image: ' + asset_name)
            shutil.copy2(asset, folder / asset.name)
        if not TECTONIC or not POPPLER:
            raise RuntimeError('找不到已安装的 Tectonic 或 PDF 渲染工具。')
        env = os.environ.copy()
        if CACHE:
            env['TECTONIC_CACHE_DIR'] = str(CACHE)
        command = [str(TECTONIC), 'report.tex', '--outdir', '.', '--synctex', '--keep-logs', '--reruns', '1', '--untrusted']
        result = subprocess.run(command, cwd=folder, env=env, capture_output=True, timeout=180)
        log = (result.stdout + result.stderr).decode('utf-8', errors='replace')
        if result.returncode or not (folder/'report.pdf').exists():
            raise RuntimeError(log[-16000:] or '编译失败。')
        rendered = subprocess.run([str(POPPLER), '-scale-to', '1650', '-png', 'report.pdf', 'page'],
                                  cwd=folder, capture_output=True, timeout=120)
        if rendered.returncode:
            raise RuntimeError(rendered.stderr.decode('utf-8',errors='replace'))
        pages = cached_preview(folder, source)
        with LOCK:
            STATE.update(pages=pages, preview_revision=revision, build_id=name, log=log[-16000:], error='')
    except Exception as exc:
        with LOCK:
            STATE.update(error=str(exc), log=str(exc))
    finally:
        with LOCK:
            try:
                cleanup_builds()
            except OSError as exc:
                STATE['log'] += '\nCache cleanup: ' + str(exc)
            STATE['busy'] = False


def begin_compile():
    with LOCK:
        if STATE['busy']:
            raise ValueError('正在编译，请稍候。')
        STATE.update(busy=True, error='')
        source, revision = SOURCE.read_text(encoding='utf-8'), STATE['revision']
        threading.Thread(target=compile_worker, args=(source,revision), daemon=True).start()


def update_source(source):
    if r'\begin{document}' not in source or r'\end{document}' not in source:
        raise ValueError('文档必须保留 document 环境。')
    parse_blocks(source)
    previous = SOURCE.read_text(encoding='utf-8')
    if previous != source:
        atomic_text(PROJECT/'report.previous.tex', previous)
        atomic_text(SOURCE, source)
        STATE['revision'] += 1
        STATE['last_saved'] = time.strftime('%H:%M:%S')


def export_tex():
    source = SOURCE.read_text(encoding='utf-8')
    content = []
    names = set(re.findall(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}', source))
    for name in sorted(names):
        path = (ASSETS/name).resolve()
        if path.parent != ASSETS.resolve() or not path.exists():
            raise ValueError(f'找不到图片：{name}')
        data = path.read_bytes()
        if path.suffix.lower() != '.pdf':
            data = image_pdf(data)
            newname = path.stem+'-export.pdf'
            source = source.replace('{'+name+'}', '{'+newname+'}')
            name = newname
        content.append(r'\begin{filecontents*}[overwrite]{'+name+'}\n'+data.decode('ascii')+r'\end{filecontents*}'+'\n')
    return source.replace(r'\begin{document}', ''.join(content)+r'\begin{document}', 1).encode('utf-8')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def local_request(self):
        port = self.server.server_address[1]
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host') not in hosts:
            self.respond({'error':'仅允许通过 localhost 或 127.0.0.1 访问。'},403)
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in {'http://'+host for host in hosts}:
            self.respond({'error':'不允许来自其他网站的请求。'},403)
            return False
        return True

    def respond(self, data, status=200, mime='application/json; charset=utf-8', filename=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.local_request():
            return
        from urllib.parse import unquote, urlsplit
        route = unquote(urlsplit(self.path).path)
        try:
            if route == '/api/state':
                self.respond(public_state()); return
            if route == '/api/export/tex':
                with LOCK:
                    self.respond(export_tex(), mime='application/x-tex; charset=utf-8', filename='report.tex')
                return
            if route == '/api/export/pdf':
                if STATE['preview_revision'] != STATE['revision']:
                    raise ValueError('修改尚未编译，请先编译最新版本。')
                self.respond((BUILD/STATE['build_id']/'report.pdf').read_bytes(), mime='application/pdf', filename='report.pdf'); return
            if route.startswith('/build/'):
                path = (BUILD/route.removeprefix('/build/')).resolve()
                if BUILD.resolve() not in path.parents or path.suffix.lower() not in ('.png','.pdf'):
                    raise ValueError('文件不可访问。')
            elif route.startswith('/assets/'):
                path = (ASSETS/route.removeprefix('/assets/')).resolve()
                if path.parent != ASSETS.resolve():
                    raise ValueError('文件不可访问。')
                if path.suffix == '.pdf':
                    images = list(PdfReader(path).pages[0].images)
                    if not images:
                        raise ValueError('此 PDF 没有可预览的图片。')
                    self.respond(images[0].data, mime=images[0].image.get_format_mimetype() or 'image/png'); return
            else:
                path = APP/'static'/('index.html' if route=='/' else route.lstrip('/'))
                if path.resolve().parent != (APP/'static').resolve():
                    raise ValueError('文件不可访问。')
            if not path.is_file():
                self.respond({'error':'文件不存在。'},404); return
            self.respond(path.read_bytes(), mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        except Exception as exc:
            self.respond({'error':str(exc)},400)

    def do_POST(self):
        if not self.local_request():
            return
        try:
            if self.headers.get('X-Editor-Token') != TOKEN:
                self.respond({'error':'请刷新编辑器后重试。'},403); return
            length = int(self.headers.get('Content-Length',0))
            if not 0 < length <= 32*1024*1024:
                raise ValueError('文件过大，请选择小于 24 MB 的图片或文档。')
            data = json.loads(self.rfile.read(length))
            with LOCK:
                if data.get('revision') != STATE['revision']:
                    self.respond({'error':'文档已在另一个页面修改，请刷新后重试。'},409); return
                source = SOURCE.read_text(encoding='utf-8')
                if self.path == '/api/compile':
                    begin_compile()
                elif self.path == '/api/new':
                    new_document(data.get('title', '未命名文档'))
                elif self.path == '/api/page-settings':
                    update_source(page_style_source(source, data['settings']))
                elif self.path == '/api/save':
                    update_source(data['source'])
                elif self.path == '/api/block':
                    block = next(b for b in parse_blocks(source) if b['id']==data['id'])
                    raw = data['source']
                    if data.get('image'):
                        binary = base64.b64decode(data['image'],validate=True)
                        pdf = image_pdf(binary)
                        name = 'image-'+secrets.token_hex(8)+'.pdf'
                        m = re.search(r'(\\includegraphics(?:\[[^\]]*\])?\{)([^}]+)(\})',raw)
                        if not m:
                            raise ValueError('此块没有 includegraphics 命令。')
                        raw = raw[:m.start(2)]+name+raw[m.end(2):]
                        (ASSETS/name).write_bytes(pdf)
                    update_source(source[:block['start']]+raw+source[block['end']:])
                elif self.path == '/api/import':
                    if STATE['busy']:
                        raise ValueError('请等待编译结束后再导入。')
                    update_source(unpack_source(data['source']))
                else:
                    self.respond({'error':'接口不存在。'},404); return
                self.respond(public_state())
        except Exception as exc:
            self.respond({'error':str(exc)},400)


def tool_path(value, executable):
    candidate = value or shutil.which(executable)
    if candidate:
        path = Path(candidate).expanduser().resolve()
        if path.is_file():
            return path
    return None


def main():
    global PROJECT, ASSETS, SOURCE, BUILD, TECTONIC, POPPLER, CACHE
    parser = argparse.ArgumentParser(description='Local visual LaTeX editor')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--project', type=Path, default=PROJECT, help='Directory for editable source, images and builds')
    parser.add_argument('--tectonic', default=os.environ.get('VISUAL_LATEX_TECTONIC'), help='Tectonic executable (default: PATH)')
    parser.add_argument('--pdftoppm', default=os.environ.get('VISUAL_LATEX_PDFTOPPM'), help='Poppler pdftoppm executable (default: PATH)')
    parser.add_argument('--cache', type=Path, default=os.environ.get('TECTONIC_CACHE_DIR'), help='Optional Tectonic cache directory')
    parser.add_argument('--check', action='store_true', help='Check dependencies and exit')
    parser.add_argument('--template', choices=['blank','example'], default='blank', help='Starter for a new project (default: blank)')
    parser.add_argument('--open', action='store_true', help='Open the editor in the default browser')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    TECTONIC = tool_path(args.tectonic, 'tectonic')
    POPPLER = tool_path(args.pdftoppm, 'pdftoppm')
    if not TECTONIC or not POPPLER:
        parser.error('Install Tectonic and Poppler, or pass --tectonic and --pdftoppm. See README.md.')
    if args.check:
        print(f'Tectonic: {TECTONIC}\nPoppler: {POPPLER}')
        return
    PROJECT = args.project.expanduser().resolve()
    ASSETS, SOURCE, BUILD = PROJECT/'assets', PROJECT/'report.tex', PROJECT/'build'
    CACHE = args.cache.expanduser().resolve() if args.cache else None
    initialize(args.template)
    httpd = ThreadingHTTPServer(('127.0.0.1',args.port), Handler)
    begin_compile()
    url = f'http://127.0.0.1:{args.port}'
    print(f'Visual LaTeX Editor: {url}\nProject: {PROJECT}\nPress Ctrl+C to stop.',flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
