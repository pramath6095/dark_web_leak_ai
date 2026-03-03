import os
import re
import asyncio
import struct
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from aiohttp import ClientSession, ClientTimeout
from aiohttp_socks import ProxyConnector

from dotenv import load_dotenv
load_dotenv()

import warnings
warnings.filterwarnings("ignore")

# tor proxy config
TOR_PROXY_HOST = os.getenv("TOR_PROXY_HOST", "127.0.0.1")
TOR_PROXY_PORT = os.getenv("TOR_PROXY_PORT", "9150")

# file extensions we care about
DOWNLOADABLE_EXTENSIONS = {
    # text/data
    '.txt', '.csv', '.tsv', '.sql', '.json', '.ndjson', '.jsonl',
    '.xml', '.log', '.yml', '.yaml',
    # config files (often contain secrets)
    '.ini', '.conf', '.cfg', '.env', '.htaccess', '.properties',
    # NOTE: .html/.htm/.php EXCLUDED — they are navigation links, not data files
    # documents
    '.pdf', '.doc', '.docx', '.xlsx', '.xls', '.pptx', '.ppt',
    '.odt', '.ods', '.odp', '.rtf',
    # archives
    '.zip', '.rar', '.7z', '.tar', '.gz', '.tar.gz', '.tgz', '.bz2',
    '.xz', '.lz', '.zst', '.cab', '.iso', '.img', '.dmg',
    # databases
    '.db', '.sqlite', '.sqlite3', '.mdb', '.accdb', '.dbf',
    '.dump', '.bak', '.sql.gz', '.sql.bz2',
    '.frm', '.ibd', '.myd', '.myi',  # mysql internals
    '.pgdump', '.psql',               # postgres
    # executables / binaries (threat by existence)
    '.exe', '.dll', '.msi', '.scr', '.com', '.pif',
    '.apk', '.ipa', '.deb', '.rpm',
    '.elf', '.bin', '.so', '.dylib',
    # scripts (potential malware)
    '.vbs', '.wsf', '.hta', '.cmd', '.reg',
    # crypto / wallets
    '.wallet', '.dat', '.key', '.pem', '.pfx', '.p12',
    '.keystore', '.jks', '.kdbx', '.kdb',
    # email / messaging
    '.eml', '.msg', '.mbox', '.pst', '.ost',
    # disk / memory
    '.vmdk', '.vhd', '.vhdx', '.qcow2',
    '.dmp', '.core', '.mem', '.raw',
    # certificates / keys
    '.crt', '.cer', '.csr', '.der',
    # misc data
    '.parquet', '.avro', '.feather', '.hdf5', '.h5',
    '.sav', '.rdata', '.rds',
    '.pcap', '.pcapng',  # network captures
    # torrents
    '.torrent',
}

# files that are inherently suspicious on dark web — threat by existence alone
THREAT_BY_EXISTENCE = {
    '.exe', '.dll', '.scr', '.pif', '.com', '.msi',  # windows executables
    '.vbs', '.wsf', '.hta', '.cmd', '.reg',           # windows scripts
    '.wallet', '.dat', '.keystore', '.kdbx',           # crypto/password stores
    '.pst', '.ost', '.mbox',                           # email archives
    '.vmdk', '.vhd', '.vhdx', '.qcow2',               # disk images
    '.dmp', '.mem', '.raw', '.core',                   # memory dumps
    '.pcap', '.pcapng',                                # network captures
    '.pem', '.pfx', '.p12', '.key', '.jks',            # private keys/certs
    '.apk', '.ipa',                                    # mobile apps
}

# magic bytes for file type detection
MAGIC_BYTES = {
    b'PK':                        'zip_archive',
    b'Rar!\x1a\x07':              'rar_archive',
    b'7z\xbc\xaf\x27\x1c':       '7z_archive',
    b'\x1f\x8b':                  'gzip',
    b'BZh':                       'bzip2',
    b'%PDF':                      'pdf',
    b'SQLite format 3':           'sqlite_database',
    b'\xd0\xcf\x11\xe0':          'ms_office_legacy',  # doc/xls
    b'\x50\x4b\x03\x04':          'zip_or_docx_xlsx',  # also office xml
    b'\x89PNG':                   'png_image',
    b'\xff\xd8\xff':              'jpeg_image',
    b'GIF8':                      'gif_image',
    b'{\n':                       'json',
    b'{\r\n':                     'json',
    b'<?xml':                     'xml',
    b'CREATE ':                   'sql_dump',
    b'INSERT ':                   'sql_dump',
    b'DROP ':                     'sql_dump',
    b'-- MySQL':                  'sql_dump',
    b'-- PostgreSQL':             'sql_dump',
    b'BEGIN TRANSACTION':         'sql_dump',
    b'd8:announce':               'torrent_file',
    b'd7:comment':                'torrent_file',
}

# max header size to download (4KB)
HEADER_SIZE = 4096

# safety limits
MAX_FILES_PER_PAGE = 5
MAX_FILES_TOTAL = 20


def get_proxy_connector(stream_id: int) -> ProxyConnector:
    return ProxyConnector.from_url(
        f"socks5://stream{stream_id}:x@{TOR_PROXY_HOST}:{TOR_PROXY_PORT}",
        rdns=True
    )


def _get_browser_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
    }


def detect_file_type(header_bytes: bytes) -> str:
    """detect file type from magic bytes in the header"""
    for magic, file_type in MAGIC_BYTES.items():
        if header_bytes.startswith(magic):
            return file_type
    
    # try to detect text-based files
    try:
        text = header_bytes[:512].decode('utf-8', errors='strict')
        # check for common text patterns
        if re.search(r'^[a-zA-Z0-9._%+\-]+@', text):
            return 'credential_list'
        if re.search(r'^[a-zA-Z0-9._%+\-]+[:|]', text, re.MULTILINE):
            return 'credential_list'
        if re.search(r'CREATE\s+TABLE|INSERT\s+INTO|SELECT\s+', text, re.IGNORECASE):
            return 'sql_dump'
        if re.search(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', text, re.MULTILINE):
            return 'ip_list'
        if ',' in text and '\n' in text:
            return 'csv_data'
        return 'text_file'
    except (UnicodeDecodeError, ValueError):
        return 'binary_unknown'


def extract_file_links(base_url: str, html: str) -> list:
    """
    extract downloadable file links and torrent/magnet links from HTML.
    filters out navigation links (.php pages, index files, etc.)
    returns list of dicts: [{url, filename, link_text, type}]
    """
    soup = BeautifulSoup(html, "html.parser")
    files = []
    seen = set()
    
    # patterns that indicate navigation, not data files
    SKIP_PATTERNS = {
        'index.', 'login.', 'register.', 'signup.', 'profile.',
        'search.', 'admin.', 'contact.', 'about.', 'faq.',
        'help.', 'rules.', 'terms.', 'privacy.', 'sitemap.',
        'page.', 'thread.', 'topic.', 'category.', 'forum.',
    }
    
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        link_text = a.get_text(strip=True)[:100]
        
        # handle magnet links
        if href.startswith('magnet:'):
            if href not in seen:
                seen.add(href)
                files.append({
                    'url': href,
                    'filename': _extract_magnet_name(href),
                    'link_text': link_text or 'magnet link',
                    'type': 'magnet',
                })
            continue
        
        # resolve relative URLs
        full_url = urljoin(base_url, href)
        
        # check for downloadable extensions
        parsed = urlparse(full_url)
        path_lower = parsed.path.lower()
        basename_lower = os.path.basename(path_lower)
        
        # skip navigation-like paths
        if any(basename_lower.startswith(p) for p in SKIP_PATTERNS):
            continue
        
        # skip if URL has typical page query params (?id=, ?page=, ?action=)
        if parsed.query and any(k in parsed.query.lower() for k in ['page=', 'id=', 'action=', 'view=', 'cat=']):
            continue
        
        matched_ext = None
        for ext in DOWNLOADABLE_EXTENSIONS:
            if path_lower.endswith(ext):
                matched_ext = ext
                break
        
        if matched_ext and full_url not in seen:
            seen.add(full_url)
            filename = os.path.basename(parsed.path) or f"file{matched_ext}"
            files.append({
                'url': full_url,
                'filename': filename,
                'link_text': link_text or filename,
                'type': 'torrent' if matched_ext == '.torrent' else 'file',
            })
        
        if len(files) >= MAX_FILES_PER_PAGE:
            break
    
    return files


# patterns that indicate the page contains threat data inline (no file links needed)
_THREAT_KEYWORDS = re.compile(
    r'(database|dump|leak|breach|combolist|stealer.?log|credential|fullz|'
    r'records|million.?user|billion.?user|sql.?dump|email.?pass|'
    r'customer.?data|citizen.?data|passport|ssn|credit.?card|'
    r'bank.?account|wallet|seed.?phrase|private.?key|'
    r'for.?sale|pay.?with|buy.?now|price|cryptocurrency)',
    re.IGNORECASE
)

def extract_inline_threats(base_url: str, text: str) -> list:
    """
    detect inline threat data on pages that don't have downloadable file links.
    marketplace listings, paste dumps, credential lists posted as text etc.
    returns list of dicts similar to file analysis results.
    """
    if not text or len(text) < 50:
        return []
    
    # count threat keyword hits
    hits = _THREAT_KEYWORDS.findall(text)
    if len(hits) < 3:
        return []
    
    # extract distinct threat items from the page
    entries = []
    
    # look for database/leak size mentions  (e.g. "533 million users", "115M records")
    size_pattern = re.compile(
        r'(\d[\d,.]*)\s*(million|billion|M|B|K|TB|GB|MB)\s*'
        r'(users?|records?|rows?|entries?|contacts?|accounts?|emails?|passwords?|citizens?|people|lines?)?',
        re.IGNORECASE
    )
    size_matches = size_pattern.findall(text)
    
    # look for price indicators (marketplace)
    price_pattern = re.compile(r'\$\s*(\d+)', re.IGNORECASE)
    prices = price_pattern.findall(text)
    
    # create a single analysis entry for the page
    entry = {
        'url': base_url,
        'file_type': 'inline_listing',
        'status': 'success',
        'threat_by_type': True,
        'extension': '',
        'link_text': '',
        'header_preview': text[:2000],
        'size_bytes': len(text),
        'inline_data': {
            'keyword_hits': len(hits),
            'unique_keywords': list(set(h.lower() for h in hits))[:15],
            'data_sizes': [f"{m[0]} {m[1]} {m[2]}".strip() for m in size_matches[:10]],
            'price_indicators': [f"${p}" for p in prices[:5]],
            'is_marketplace': len(prices) > 0,
        }
    }
    entries.append(entry)
    
    return entries


def _extract_magnet_name(magnet_uri: str) -> str:
    """extract display name from magnet URI"""
    match = re.search(r'dn=([^&]+)', magnet_uri)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1)).replace('+', ' ')
    
    # extract info hash as fallback
    match = re.search(r'btih:([a-fA-F0-9]{40})', magnet_uri)
    if match:
        return f"torrent_{match.group(1)[:12]}"
    
    return "unknown_magnet"


def _extract_magnet_metadata(magnet_uri: str) -> dict:
    """extract all available metadata from magnet URI"""
    info = {
        'type': 'magnet_link',
        'name': _extract_magnet_name(magnet_uri),
        'info_hash': None,
        'trackers': [],
        'size': None,
    }
    
    # info hash
    match = re.search(r'btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})', magnet_uri)
    if match:
        info['info_hash'] = match.group(1)
    
    # trackers
    for match in re.finditer(r'tr=([^&]+)', magnet_uri):
        from urllib.parse import unquote
        info['trackers'].append(unquote(match.group(1)))
    
    # size (xl parameter)
    match = re.search(r'xl=(\d+)', magnet_uri)
    if match:
        info['size'] = int(match.group(1))
    
    return info


def _parse_torrent_file(data: bytes) -> dict:
    """parse a .torrent file to extract file listing and metadata"""
    try:
        import bencodepy
        decoded = bencodepy.decode(data)
        
        info = decoded.get(b'info', {})
        result = {
            'type': 'torrent_file',
            'name': info.get(b'name', b'unknown').decode('utf-8', errors='replace'),
            'files': [],
            'total_size': 0,
            'comment': decoded.get(b'comment', b'').decode('utf-8', errors='replace'),
            'created_by': decoded.get(b'created by', b'').decode('utf-8', errors='replace'),
        }
        
        # multi-file torrent
        if b'files' in info:
            for f in info[b'files']:
                path_parts = [p.decode('utf-8', errors='replace') for p in f.get(b'path', [])]
                file_path = '/'.join(path_parts)
                file_size = f.get(b'length', 0)
                result['files'].append({
                    'path': file_path,
                    'size': file_size,
                    'extension': os.path.splitext(file_path)[1].lower(),
                })
                result['total_size'] += file_size
        else:
            # single-file torrent
            size = info.get(b'length', 0)
            result['files'].append({
                'path': result['name'],
                'size': size,
                'extension': os.path.splitext(result['name'])[1].lower(),
            })
            result['total_size'] = size
        
        return result
    except Exception as e:
        return {'type': 'torrent_file', 'error': str(e)[:100], 'files': []}


async def download_file_header(url: str, stream_id: int) -> dict:
    """
    download only the first 4KB of a file via HTTP Range request.
    returns dict with file type, header preview, and metadata.
    """
    connector = get_proxy_connector(stream_id)
    timeout = ClientTimeout(total=15)
    headers = _get_browser_headers()
    headers['Range'] = f'bytes=0-{HEADER_SIZE - 1}'
    
    result = {
        'url': url,
        'status': 'error',
        'file_type': 'unknown',
        'size_bytes': 0,
        'header_preview': '',
        'content_type': '',
    }
    
    try:
        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                # accept both 200 (full file) and 206 (partial content)
                if response.status not in (200, 206):
                    result['status'] = f'http_{response.status}'
                    return result
                
                # get content info
                result['content_type'] = response.headers.get('Content-Type', '')
                total_size = response.headers.get('Content-Range', '')
                if total_size:
                    match = re.search(r'/(\d+)', total_size)
                    if match:
                        result['size_bytes'] = int(match.group(1))
                elif response.headers.get('Content-Length'):
                    result['size_bytes'] = int(response.headers['Content-Length'])
                
                # read only header bytes
                data = await response.content.read(HEADER_SIZE)
                
                # reject HTML pages served by web servers (e.g. .php pages)
                content_type = result['content_type'].lower()
                if 'text/html' in content_type:
                    data_start = data[:100].decode('utf-8', errors='replace').strip().lower()
                    if data_start.startswith(('<!doctype', '<html', '<head', '<?xml')):
                        result['file_type'] = 'html_page'
                        result['status'] = 'skipped_html'
                        return result
                
                # detect type from magic bytes
                result['file_type'] = detect_file_type(data)
                result['status'] = 'success'
                
                # generate preview
                try:
                    text = data.decode('utf-8', errors='replace')
                    # clean up and truncate for preview
                    lines = text.split('\n')[:20]  # first 20 lines
                    result['header_preview'] = '\n'.join(lines)[:2000]
                except Exception:
                    # hex dump for binary files
                    hex_lines = []
                    for i in range(0, min(len(data), 256), 16):
                        hex_part = ' '.join(f'{b:02x}' for b in data[i:i+16])
                        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[i:i+16])
                        hex_lines.append(f'{i:04x}: {hex_part:<48} {ascii_part}')
                    result['header_preview'] = '\n'.join(hex_lines)
                
                return result
                
    except asyncio.TimeoutError:
        result['status'] = 'timeout'
        return result
    except Exception as e:
        result['status'] = f'error: {str(e)[:80]}'
        return result


async def download_torrent_metadata(url: str, stream_id: int) -> dict:
    """download a .torrent file and parse its metadata (file listing)"""
    connector = get_proxy_connector(stream_id)
    timeout = ClientTimeout(total=15)
    headers = _get_browser_headers()
    
    try:
        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return {'type': 'torrent_file', 'error': f'HTTP {response.status}', 'files': []}
                
                # torrent files are small, but cap at 1MB
                data = await response.content.read(1024 * 1024)
                return _parse_torrent_file(data)
                
    except Exception as e:
        return {'type': 'torrent_file', 'error': str(e)[:80], 'files': []}


async def analyze_threat_files_async(
    html_cache: dict, 
    classifications: dict, 
    max_workers: int = 3
) -> dict:
    """
    main entry point: analyze files from threat-classified pages.
    
    1. filters pages classified as threats
    2. extracts file links from their HTML
    3. downloads headers / torrent metadata
    4. returns structured analysis results
    """
    # scan all classified pages for files — the AI file verification step
    # will determine if the files are real threats from their content
    threat_urls = list(classifications.keys())
    
    if not threat_urls:
        print("  [*] No classified pages to analyze for files")
        return {}
    
    print(f"  [*] Scanning {len(threat_urls)} threat pages for downloadable files...")
    
    # extract file links from threat pages
    all_file_links = {}
    total_files = 0
    
    for url in threat_urls:
        html = html_cache.get(url, '')
        if not html:
            continue
        
        links = extract_file_links(url, html)
        if links:
            all_file_links[url] = links
            total_files += len(links)
            print(f"  [+] {url[:45]}... → {len(links)} files found")
        
        if total_files >= MAX_FILES_TOTAL:
            print(f"  [!] Hit max file limit ({MAX_FILES_TOTAL})")
            break
    
    if not all_file_links:
        # no downloadable files — try detecting inline threat data (marketplace listings, paste dumps)
        print("  [*] No downloadable files found, scanning for inline threat data...")
        inline_results = {}
        for url in threat_urls:
            html = html_cache.get(url, '')
            if not html:
                continue
            threats = extract_inline_threats(url, html)
            for t in threats:
                inline_results[t['url']] = t
                print(f"  [+] {url[:45]}... -> inline listing ({t['inline_data']['keyword_hits']} threat keywords)")
        
        if inline_results:
            print(f"\n  [+] Found {len(inline_results)} pages with inline threat data")
            return inline_results
        
        print("  [*] No threat data found on any pages")
        return {}
    
    print(f"\n  [*] Sampling headers from {total_files} files...")
    
    # download headers and torrent metadata
    semaphore = asyncio.Semaphore(max_workers)
    results = {}
    stream_counter = 100  # offset to avoid collision with scrape circuits
    
    async def limited_analyze(file_info, sid):
        async with semaphore:
            url = file_info['url']
            ftype = file_info['type']
            
            # check if file extension alone makes it a threat
            ext = os.path.splitext(file_info['filename'])[1].lower()
            threat_flag = ext in THREAT_BY_EXISTENCE
            
            if ftype == 'magnet':
                result = _extract_magnet_metadata(url)
            elif ftype == 'torrent':
                result = await download_torrent_metadata(url, sid)
            else:
                result = await download_file_header(url, sid)
            
            if isinstance(result, dict):
                result['threat_by_type'] = threat_flag
                result['extension'] = ext
                result['link_text'] = file_info.get('link_text', '')
            
            return file_info['url'], result
    
    tasks = []
    for page_url, links in all_file_links.items():
        for file_info in links:
            tasks.append(limited_analyze(file_info, stream_counter))
            stream_counter += 1
    
    task_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for result in task_results:
        if isinstance(result, tuple):
            file_url, analysis = result
            
            # skip HTML pages that got through
            if isinstance(analysis, dict) and analysis.get('status') == 'skipped_html':
                print(f"  [-] {file_url[:50]}... → skipped (HTML page)")
                continue
            
            results[file_url] = analysis
            
            # print status
            if isinstance(analysis, dict):
                ftype = analysis.get('file_type', analysis.get('type', 'unknown'))
                status = analysis.get('status', 'ok')
                if status == 'success' or 'files' in analysis:
                    print(f"  [+] {file_url[:50]}... → {ftype}")
                else:
                    print(f"  [!] {file_url[:50]}... → {status}")
        elif isinstance(result, Exception):
            print(f"  [!] Analysis error: {str(result)[:60]}")
    
    return results


def analyze_threat_files(html_cache: dict, classifications: dict, max_workers: int = 3) -> dict:
    """sync wrapper for analyze_threat_files_async — creates new event loop to avoid conflicts"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            analyze_threat_files_async(html_cache, classifications, max_workers)
        )
    finally:
        loop.close()


def format_file_analysis(results: dict, verdicts: dict = None) -> str:
    """format file analysis results into readable text for output file"""
    if not results:
        return "No files analyzed."
    
    lines = []
    lines.append("=" * 60)
    lines.append("FILE ANALYSIS REPORT")
    lines.append("=" * 60)
    
    for i, (url, analysis) in enumerate(results.items(), 1):
        lines.append(f"\n{'─' * 60}")
        lines.append(f"[{i}] {url[:80]}")
        lines.append(f"{'─' * 60}")
        
        if isinstance(analysis, dict):
            atype = analysis.get('type', analysis.get('file_type', 'unknown'))
            lines.append(f"  Type: {atype}")
            
            if analysis.get('extension'):
                lines.append(f"  Extension: {analysis['extension']}")
            
            if analysis.get('link_text'):
                lines.append(f"  Link Text: {analysis['link_text']}")
            
            if analysis.get('threat_by_type'):
                lines.append(f"  !! THREAT BY FILE TYPE -- inherently suspicious on dark web")
            
            # inline threat data (marketplace listings, paste dumps)
            if 'inline_data' in analysis:
                idata = analysis['inline_data']
                lines.append(f"  ** INLINE THREAT DATA DETECTED ({idata['keyword_hits']} threat keyword hits)")
                if idata.get('is_marketplace'):
                    lines.append(f"  ** This is a MARKETPLACE listing")
                if idata.get('data_sizes'):
                    lines.append(f"  Data sizes mentioned: {', '.join(idata['data_sizes'][:8])}")
                if idata.get('price_indicators'):
                    lines.append(f"  Prices listed: {', '.join(idata['price_indicators'])}")
                if idata.get('unique_keywords'):
                    lines.append(f"  Threat keywords: {', '.join(idata['unique_keywords'][:10])}")
            
            if 'size_bytes' in analysis and analysis['size_bytes']:
                size = analysis['size_bytes']
                if size > 1024 * 1024:
                    lines.append(f"  Size: {size / (1024*1024):.1f} MB")
                elif size > 1024:
                    lines.append(f"  Size: {size / 1024:.1f} KB")
                else:
                    lines.append(f"  Size: {size} bytes")
            
            if 'total_size' in analysis:
                size = analysis['total_size']
                if size > 1024 * 1024:
                    lines.append(f"  Total Size: {size / (1024*1024):.1f} MB")
                elif size > 1024:
                    lines.append(f"  Total Size: {size / 1024:.1f} KB")
            
            if 'files' in analysis and analysis['files']:
                lines.append(f"  Files in archive/torrent ({len(analysis['files'])}):")
                for f in analysis['files'][:10]:
                    fsize = f.get('size', 0)
                    if fsize > 1024 * 1024:
                        size_str = f"{fsize / (1024*1024):.1f} MB"
                    elif fsize > 1024:
                        size_str = f"{fsize / 1024:.1f} KB"
                    else:
                        size_str = f"{fsize} bytes"
                    lines.append(f"    • {f['path']} ({size_str})")
                if len(analysis['files']) > 10:
                    lines.append(f"    ... and {len(analysis['files']) - 10} more")
            
            if 'header_preview' in analysis and analysis['header_preview']:
                preview = analysis['header_preview'][:500]
                lines.append(f"  Header Preview:")
                for line in preview.split('\n')[:10]:
                    lines.append(f"    | {line}")
            
            if 'name' in analysis:
                lines.append(f"  Name: {analysis['name']}")
            
            if 'info_hash' in analysis and analysis['info_hash']:
                lines.append(f"  Info Hash: {analysis['info_hash']}")
            
            if 'error' in analysis:
                lines.append(f"  Error: {analysis['error']}")
        
        # add verdict if available
        if verdicts and url in verdicts:
            v = verdicts[url]
            lines.append(f"\n  AI VERDICT: {v.get('verdict', 'unknown').upper()}")
            lines.append(f"  Confidence: {v.get('confidence', 'N/A')}")
            lines.append(f"  Reason: {v.get('reason', 'N/A')}")
    
    return '\n'.join(lines)
