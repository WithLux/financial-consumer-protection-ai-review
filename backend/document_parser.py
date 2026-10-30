"""Bounded parsing; upload bytes are never persisted as original files."""
import io
import multiprocessing as mp
import sys
import zipfile
from pathlib import Path

class ParseError(Exception):
    def __init__(self,code,message,status=422):
        self.code,self.message,self.status=code,message,status
        super().__init__(message)


def parse_bytes(filename,data):
    if not data:raise ParseError('empty_file','文件为空')
    if len(data)>10*1024*1024:raise ParseError('file_too_large','文件超过10 MiB',413)
    ext=Path(filename).suffix.lower();items=[];warnings=[]
    def add(text,locator):
        if text.strip():items.append({'segment_id':f's{len(items)+1}','text':text,'locator':locator})
    try:
        if ext=='.txt':
            if data.startswith((b'%PDF-',b'PK\x03\x04')) or b'\0' in data:raise ParseError('type_mismatch','TXT实际内容为二进制或其他文档格式',415)
            try:text=data.decode('utf-8-sig')
            except UnicodeDecodeError:raise ParseError('unsupported_encoding','仅支持UTF-8或UTF-8 BOM编码')
            for n,line in enumerate(text.splitlines()):add(line,{'kind':'line','line':n+1})
        elif ext=='.pdf':
            if not data.startswith(b'%PDF-'):raise ParseError('type_mismatch','文件不是有效PDF',415)
            try:import fitz
            except ImportError:raise ParseError('parser_unavailable','PDF解析组件PyMuPDF尚未安装',503)
            with fitz.open(stream=data,filetype='pdf') as doc:
                if doc.needs_pass:raise ParseError('encrypted_pdf','加密PDF不支持，请提供未加密版本')
                if len(doc)>100:raise ParseError('parse_limit','PDF超过100页解析限制')
                for n,page in enumerate(doc):
                    blocks=page.get_text('blocks',sort=True);nonempty=False
                    for block in blocks:
                        if len(block)>6 and block[6]!=0:continue
                        if str(block[4]).strip():add(str(block[4]),{'kind':'page','page':n+1});nonempty=True
                    if not nonempty:warnings.append(f'第{n+1}页无可提取文本，可能为空白或扫描页，未进行OCR')
                if not items:raise ParseError('scanned_pdf','PDF无可提取文本，扫描件需另行OCR')
        elif ext=='.docx':
            if not zipfile.is_zipfile(io.BytesIO(data)):raise ParseError('type_mismatch','DOCX不是有效Office ZIP文件',415)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                info=archive.infolist()
                if len(info)>1000 or sum(i.file_size for i in info)>50*1024*1024:raise ParseError('parse_limit','DOCX解压内容超过限制')
                if not {'[Content_Types].xml','word/document.xml'}.issubset(archive.namelist()):raise ParseError('type_mismatch','ZIP内容不是DOCX',415)
                if any(i.flag_bits&1 for i in info):raise ParseError('encrypted_docx','不支持加密DOCX')
            try:
                from docx import Document
                from docx.text.paragraph import Paragraph
                from docx.table import Table
            except ImportError:raise ParseError('parser_unavailable','DOCX解析组件python-docx尚未安装',503)
            doc=Document(io.BytesIO(data));paragraph=table=0
            for child in doc.element.body.iterchildren():
                if child.tag.endswith('}p'):
                    paragraph+=1;add(Paragraph(child,doc).text,{'kind':'paragraph','paragraph':paragraph})
                elif child.tag.endswith('}tbl'):
                    table+=1
                    for rn,row in enumerate(Table(child,doc).rows):
                        seen=set()
                        for cn,cell in enumerate(row.cells):
                            if cell._tc in seen:continue
                            seen.add(cell._tc);add(cell.text,{'kind':'cell','table':table,'row':rn+1,'cell':cn+1})
            warnings.append('DOCX提取正文和表格；页眉、页脚、文本框、图片及修订内容未完整覆盖，不提供稳定页码')
        else:raise ParseError('unsupported_type','只支持PDF、DOCX、TXT',415)
    except ParseError:raise
    except Exception:raise ParseError('corrupt_file','文件损坏或内容无法解析') from None
    if not items:raise ParseError('empty_text','文件没有可用文本')
    offset=0
    for item in items:
        item['document_offset']=offset;offset+=len(item['text'])+1
    if offset>100001:raise ParseError('parse_limit','提取文本超过10万码点，不进行静默截断')
    return {'segments':items,'coverage':{'complete':not warnings,'warnings':warnings}}


def _worker(connection,filename,data):
    try:
        # Linux supports address-space limits reliably; macOS uses size/page/time bounds.
        if sys.platform.startswith('linux'):
            import resource
            resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
        connection.send(('ok',parse_bytes(filename,data)))
    except ParseError as e:connection.send(('error',(e.code,e.message,e.status)))
    except BaseException:connection.send(('error',('parser_failed','解析子进程失败',422)))
    finally:connection.close()


def parse_document(filename,data,timeout=15):
    ctx=mp.get_context('spawn');parent,child=ctx.Pipe(duplex=False)
    process=ctx.Process(target=_worker,args=(child,filename,data),daemon=True)
    process.start();child.close()
    try:
        if not parent.poll(timeout):raise ParseError('parse_timeout','文件解析超时，已终止处理')
        try:status,result=parent.recv()
        except EOFError:raise ParseError('parser_failed','解析进程异常退出')
        if status=='error':raise ParseError(*result)
        return result
    finally:
        parent.close()
        if process.is_alive():process.terminate()
        process.join(2)
        if process.is_alive():process.kill();process.join()
