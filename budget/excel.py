import io
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

_SPREADSHEET_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_PKG_REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'

_CELL_REF_RE = re.compile(r'^([A-Za-z]+)(\d+)$')
_INVALID_SHEET_CHARS_RE = re.compile(r'[\\/?*\[\]:]')


def _local_name(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _col_index_to_letter(idx):
    """Convert 0-based column index to Excel column letters (0 -> 'A', 26 -> 'AA')."""
    letters = []
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return ''.join(reversed(letters))


def _col_letter_to_index(letters):
    """Convert Excel column letters to 0-based column index ('A' -> 0, 'AA' -> 26)."""
    idx = 0
    for ch in letters.upper():
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _sanitize_sheet_name(name, index):
    cleaned = _INVALID_SHEET_CHARS_RE.sub('_', (name or '').strip())[:31]
    return cleaned or f'Sheet{index}'


def _needs_xml_space_preserve(text):
    return bool(text) and (text[0].isspace() or text[-1].isspace() or '\n' in text or '\r' in text)


def _format_numeric_string(raw):
    if raw is None:
        return ''
    text = raw.strip()
    if not text:
        return ''
    try:
        num = float(text)
        if num.is_integer():
            return str(int(num))
    except ValueError:
        pass
    return text


def build_xlsx(sheets):
    """Build a valid .xlsx workbook bytes object from [(sheet_name, rows), ...]."""
    shared_strings = []
    shared_index = {}

    def intern_string(value):
        s = str(value)
        idx = shared_index.get(s)
        if idx is None:
            idx = len(shared_strings)
            shared_index[s] = idx
            shared_strings.append(s)
        return idx

    prepared_sheets = []
    for i, (raw_name, rows) in enumerate(sheets, start=1):
        name = _sanitize_sheet_name(raw_name, i)
        prepared_sheets.append((name, rows or []))

    content_types_overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>',
    ]
    workbook_sheets_xml = []
    workbook_rels_xml = []
    worksheet_xmls = {}

    for i, (sheet_name, rows) in enumerate(prepared_sheets, start=1):
        rid = f'rId{i}'
        part_path = f'xl/worksheets/sheet{i}.xml'
        content_types_overrides.append(
            f'<Override PartName="/{part_path}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        workbook_sheets_xml.append(
            f'<sheet name="{escape(sheet_name)}" sheetId="{i}" r:id="{rid}"/>'
        )
        workbook_rels_xml.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        )

        # Compute column widths for readability
        col_widths = {}
        row_xml_parts = []
        for r_idx, row in enumerate(rows, start=1):
            cell_xml_parts = []
            style_attr = ' s="1"' if r_idx == 1 else ''
            for c_idx, val in enumerate(row):
                if val is None or val == '':
                    if r_idx == 1:
                        # Keep empty header styled consistently if ever present
                        s_idx = intern_string('')
                        ref = f'{_col_index_to_letter(c_idx)}{r_idx}'
                        cell_xml_parts.append(f'<c r="{ref}" t="s"{style_attr}><v>{s_idx}</v></c>')
                    continue

                ref = f'{_col_index_to_letter(c_idx)}{r_idx}'
                text_len = len(str(val))
                if text_len > col_widths.get(c_idx, 0):
                    col_widths[c_idx] = text_len

                if isinstance(val, bool):
                    b_val = '1' if val else '0'
                    cell_xml_parts.append(f'<c r="{ref}" t="b"{style_attr}><v>{b_val}</v></c>')
                elif isinstance(val, (int, float)):
                    cell_xml_parts.append(f'<c r="{ref}"{style_attr}><v>{val}</v></c>')
                else:
                    s_idx = intern_string(val)
                    cell_xml_parts.append(f'<c r="{ref}" t="s"{style_attr}><v>{s_idx}</v></c>')

            if cell_xml_parts:
                row_xml_parts.append(f'<row r="{r_idx}">{"".join(cell_xml_parts)}</row>')

        cols_xml = ''
        if col_widths:
            col_defs = []
            for c_idx in sorted(col_widths):
                width = max(14, min(46, col_widths[c_idx] + 4))
                col_num = c_idx + 1
                col_defs.append(f'<col min="{col_num}" max="{col_num}" width="{width}" customWidth="1"/>')
            cols_xml = f'<cols>{"".join(col_defs)}</cols>'

        tab_selected = ' tabSelected="1"' if i == 1 else ''
        sheet_views_xml = (
            f'<sheetViews><sheetView{tab_selected} workbookViewId="0">'
            f'<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            f'</sheetView></sheetViews>'
        )

        worksheet_xmls[part_path] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{_SPREADSHEET_NS}">'
            f'{sheet_views_xml}'
            f'{cols_xml}'
            f'<sheetData>{"".join(row_xml_parts)}</sheetData>'
            '</worksheet>'
        )

    styles_rid = f'rId{len(prepared_sheets) + 1}'
    strings_rid = f'rId{len(prepared_sheets) + 2}'
    workbook_rels_xml.append(
        f'<Relationship Id="{styles_rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    workbook_rels_xml.append(
        f'<Relationship Id="{strings_rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{"".join(content_types_overrides)}'
        '</Types>'
    )

    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PKG_REL_NS}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{_SPREADSHEET_NS}" xmlns:r="{_REL_NS}">'
        f'<sheets>{"".join(workbook_sheets_xml)}</sheets>'
        '</workbook>'
    )

    workbook_rels_doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PKG_REL_NS}">'
        f'{"".join(workbook_rels_xml)}'
        '</Relationships>'
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{_SPREADSHEET_NS}">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1E293B"/></patternFill></fill>'
        '</fills>'
        '<borders count="1">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '</cellXfs>'
        '</styleSheet>'
    )

    si_parts = []
    for text in shared_strings:
        preserve = ' xml:space="preserve"' if _needs_xml_space_preserve(text) else ''
        si_parts.append(f'<si><t{preserve}>{escape(text)}</t></si>')

    shared_strings_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="{_SPREADSHEET_NS}" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        f'{"".join(si_parts)}'
        '</sst>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types_xml.encode('utf-8'))
        zf.writestr('_rels/.rels', root_rels_xml.encode('utf-8'))
        zf.writestr('xl/workbook.xml', workbook_xml.encode('utf-8'))
        zf.writestr('xl/_rels/workbook.xml.rels', workbook_rels_doc.encode('utf-8'))
        zf.writestr('xl/styles.xml', styles_xml.encode('utf-8'))
        zf.writestr('xl/sharedStrings.xml', shared_strings_xml.encode('utf-8'))
        for path, xml_str in worksheet_xmls.items():
            zf.writestr(path, xml_str.encode('utf-8'))
    return buf.getvalue()


def _read_shared_strings(zf):
    if 'xl/sharedStrings.xml' not in zf.namelist():
        return []
    root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
    strings = []
    for si in root:
        if _local_name(si.tag) != 'si':
            continue
        parts = []
        for elem in si.iter():
            if _local_name(elem.tag) == 't' and elem.text:
                parts.append(elem.text)
        strings.append(''.join(parts))
    return strings


def _resolve_sheet_targets(zf):
    if 'xl/workbook.xml' not in zf.namelist():
        raise ValueError('Invalid Excel (.xlsx) file: missing workbook definition.')

    rel_map = {}
    if 'xl/_rels/workbook.xml.rels' in zf.namelist():
        rels_root = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
        for rel in rels_root:
            if _local_name(rel.tag) != 'Relationship':
                continue
            rid = rel.attrib.get('Id')
            target = (rel.attrib.get('Target') or '').lstrip('/')
            if rid and target:
                if not target.startswith('xl/'):
                    target = f'xl/{target}'
                rel_map[rid] = target

    wb_root = ET.fromstring(zf.read('xl/workbook.xml'))
    sheets = []
    for elem in wb_root.iter():
        if _local_name(elem.tag) != 'sheet':
            continue
        name = elem.attrib.get('name') or f'Sheet{len(sheets) + 1}'
        rid = None
        for attr_key, attr_val in elem.attrib.items():
            if _local_name(attr_key) == 'id':
                rid = attr_val
                break
        target = rel_map.get(rid) if rid else None
        if not target:
            fallback = f'xl/worksheets/sheet{len(sheets) + 1}.xml'
            if fallback in zf.namelist():
                target = fallback
        if target and target in zf.namelist():
            sheets.append((name, target))
    return sheets


def _extract_cell_value(cell_elem, shared_strings):
    cell_type = cell_elem.attrib.get('t', '')
    if cell_type == 'inlineStr':
        parts = [
            elem.text for elem in cell_elem.iter()
            if _local_name(elem.tag) == 't' and elem.text
        ]
        return ''.join(parts)

    v_text = None
    for child in cell_elem:
        if _local_name(child.tag) == 'v':
            v_text = child.text
            break

    if v_text is None:
        return ''

    if cell_type == 's':
        try:
            idx = int(v_text)
            return shared_strings[idx] if 0 <= idx < len(shared_strings) else ''
        except ValueError:
            return ''
    if cell_type == 'b':
        return 'YES' if v_text.strip() == '1' else 'NO'
    if cell_type in ('str', 'e'):
        return v_text
    return _format_numeric_string(v_text)


def parse_xlsx(file_obj):
    """Parse an .xlsx file-like object into an ordered list of (sheet_name, rows)."""
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    try:
        raw_bytes = file_obj.read()
        if not raw_bytes:
            raise ValueError('The uploaded Excel file is empty.')
        zf = zipfile.ZipFile(io.BytesIO(raw_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError('Invalid Excel (.xlsx) file. Please download and fill the .xlsx template.') from exc

    try:
        with zf:
            shared_strings = _read_shared_strings(zf)
            sheet_targets = _resolve_sheet_targets(zf)
            if not sheet_targets:
                raise ValueError('No worksheets found in the uploaded Excel file.')

            parsed_sheets = []
            for sheet_name, target in sheet_targets:
                root = ET.fromstring(zf.read(target))
                rows_by_num = {}
                max_row = 0

                for elem in root.iter():
                    if _local_name(elem.tag) != 'row':
                        continue
                    row_num_attr = elem.attrib.get('r')
                    if row_num_attr and row_num_attr.isdigit():
                        row_num = int(row_num_attr)
                    else:
                        row_num = max_row + 1
                    max_row = max(max_row, row_num)

                    cells = {}
                    seq_col = 0
                    for child in elem:
                        if _local_name(child.tag) != 'c':
                            continue
                        ref = child.attrib.get('r', '')
                        m = _CELL_REF_RE.match(ref)
                        if m:
                            col_idx = _col_letter_to_index(m.group(1))
                        else:
                            col_idx = seq_col
                        seq_col = col_idx + 1
                        cells[col_idx] = _extract_cell_value(child, shared_strings)

                    if cells:
                        width = max(cells) + 1
                        row_vals = [cells.get(i, '') for i in range(width)]
                        while row_vals and row_vals[-1] == '':
                            row_vals.pop()
                        rows_by_num[row_num] = row_vals

                if not rows_by_num:
                    parsed_sheets.append((sheet_name, []))
                    continue

                rows = [rows_by_num.get(r, []) for r in range(1, max_row + 1)]
                while rows and not any(str(c).strip() for c in rows[-1]):
                    rows.pop()
                parsed_sheets.append((sheet_name, rows))

            return parsed_sheets
    except (ET.ParseError, KeyError, zipfile.BadZipFile) as exc:
        raise ValueError('Could not read the Excel (.xlsx) file. Please ensure it is a valid .xlsx workbook.') from exc
