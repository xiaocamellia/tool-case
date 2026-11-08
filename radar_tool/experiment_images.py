"""Safe experiment image path and image header validation."""
import ntpath
import os
import re
import stat
import struct

from . import exp_recorder as _context

def _is_within_directory(root, candidate):
    root_path = os.path.normcase(os.path.abspath(root))
    candidate_path = os.path.normcase(os.path.abspath(candidate))
    try:
        return os.path.commonpath([root_path, candidate_path]) == root_path
    except ValueError:
        return False
def _contains_symlink_component(root, candidate):
    try:
        relative = os.path.relpath(candidate, root)
    except ValueError:
        return True
    current = root
    for part in relative.split(os.sep):
        if not part or part == os.curdir:
            continue
        if part == os.pardir:
            return True
        current = os.path.join(current, part)
        try:
            if os.path.islink(current):
                return True
        except OSError:
            return True
    return False
def _resolve_images_root():
    root = os.path.realpath(os.path.abspath(_context.IMAGES_DIR))
    os.makedirs(root, exist_ok=True)
    return root
def _resolve_inside_images_dir(path, must_exist=True):
    if not isinstance(path, str) or not path:
        raise ValueError('图片路径不能为空')
    root = _resolve_images_root()
    if os.path.isabs(path) or ntpath.isabs(path):
        candidate = os.path.abspath(path)
    else:
        drive, _ = ntpath.splitdrive(path)
        if drive:
            raise ValueError('图片相对路径不得包含盘符')
        parts = re.split(r'[\\/]+', path)
        if any(part in ('', os.curdir, os.pardir) for part in parts):
            raise ValueError('图片相对路径不得包含空目录、`.` 或 `..`')
        candidate = os.path.join(root, *parts)
    resolved = os.path.realpath(candidate)
    if not _is_within_directory(root, resolved):
        raise ValueError('图片路径超出允许的图片目录')
    if _contains_symlink_component(root, candidate):
        raise ValueError('图片路径包含符号链接')
    if must_exist:
        try:
            file_stat = os.lstat(candidate)
        except OSError as exc:
            raise ValueError('图片文件不存在或不可访问') from exc
        if stat.S_ISLNK(file_stat.st_mode):
            raise ValueError('图片路径不得指向符号链接')
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError('图片路径必须指向普通文件')
    return resolved
def _tiff_dimensions(path):
    with open(path, 'rb') as handle:
        header = handle.read(8)
        if len(header) < 8:
            raise ValueError('TIFF 文件头无效')
        if header[:4] == b'II*\x00':
            endian = '<'
        elif header[:4] == b'MM\x00*':
            endian = '>'
        else:
            raise ValueError('TIFF 文件头无效')
        directory_offset = struct.unpack(endian + 'I', header[4:8])[0]
        if directory_offset < 8:
            raise ValueError('TIFF 目录偏移无效')
        handle.seek(directory_offset)
        raw_count = handle.read(2)
        if len(raw_count) != 2:
            raise ValueError('TIFF 目录不完整')
        entry_count = struct.unpack(endian + 'H', raw_count)[0]
        if entry_count > _context.MAX_TIFF_DIRECTORY_ENTRIES:
            raise ValueError('TIFF 目录条目过多')
        width = height = 0
        for _ in range(entry_count):
            entry = handle.read(12)
            if len(entry) != 12:
                raise ValueError('TIFF 目录条目不完整')
            tag, value_type, value_count = struct.unpack(endian + 'HHI', entry[:8])
            if tag not in (256, 257) or value_count != 1 or value_type not in (3, 4):
                continue
            if value_type == 3:
                value = struct.unpack(endian + 'H', entry[8:10])[0]
            else:
                value = struct.unpack(endian + 'I', entry[8:12])[0]
            if tag == 256:
                width = value
            else:
                height = value
        if width <= 0 or height <= 0:
            raise ValueError('TIFF 文件头中未找到有效尺寸')
        if width * height > _context.MAX_IMAGE_PIXELS:
            raise ValueError(f'图片像素数超过上限 {_context.MAX_IMAGE_PIXELS}')
        return width, height
def _image_dimensions_from_header(header, extension):
    if extension == '.png':
        if len(header) < 24 or header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
            raise ValueError('PNG 文件头无效')
        width, height = struct.unpack('>II', header[16:24])
    elif extension in ('.jpg', '.jpeg'):
        if len(header) < 4 or header[:3] != b'\xff\xd8\xff':
            raise ValueError('JPEG 文件头无效')
        position = 2
        width = height = 0
        sof_markers = {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }
        while position + 4 <= len(header):
            if header[position] != 0xFF:
                position += 1
                continue
            marker = header[position + 1]
            if marker in (0x01, 0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                position += 2
                continue
            segment_length = struct.unpack('>H', header[position + 2:position + 4])[0]
            if segment_length < 2:
                raise ValueError('JPEG 段长度无效')
            if marker in sof_markers:
                if position + 9 > len(header):
                    break
                height = struct.unpack('>H', header[position + 5:position + 7])[0]
                width = struct.unpack('>H', header[position + 7:position + 9])[0]
                break
            position += 2 + segment_length
        if not width or not height:
            raise ValueError('JPEG 文件头中未找到有效尺寸')
    elif extension == '.bmp':
        if len(header) < 26 or header[:2] != b'BM':
            raise ValueError('BMP 文件头无效')
        dib_size = struct.unpack('<I', header[14:18])[0]
        if dib_size == 12:
            if len(header) < 22:
                raise ValueError('BMP 文件头过短')
            width, height = struct.unpack('<HH', header[18:22])
        elif dib_size >= 40:
            if len(header) < 34:
                raise ValueError('BMP 文件头过短')
            width, height = struct.unpack('<ii', header[18:26])
            height = abs(height)
        else:
            raise ValueError('不支持的 BMP DIB 头')
    elif extension in ('.tif', '.tiff'):
        raise RuntimeError('TIFF 尺寸必须通过文件解析')
    elif extension == '.webp':
        if len(header) < 12 or header[:4] != b'RIFF' or header[8:12] != b'WEBP':
            raise ValueError('WebP 文件头无效')
        chunk = header[12:16]
        if chunk == b'VP8X':
            if len(header) < 30:
                raise ValueError('WebP VP8X 帧头无效')
            width = int.from_bytes(header[24:27], 'little') + 1
            height = int.from_bytes(header[27:30], 'little') + 1
        elif chunk == b'VP8 ':
            if len(header) < 30 or header[23:26] != b'\x9d\x01\x2a':
                raise ValueError('WebP VP8 帧头无效')
            width = struct.unpack('<H', header[26:28])[0] & 0x3FFF
            height = struct.unpack('<H', header[28:30])[0] & 0x3FFF
        elif chunk == b'VP8L':
            if len(header) < 25 or header[20] != 0x2F:
                raise ValueError('WebP VP8L 帧头无效')
            packed = int.from_bytes(header[21:25], 'little')
            width = (packed & 0x3FFF) + 1
            height = ((packed >> 14) & 0x3FFF) + 1
        else:
            raise ValueError('不支持的 WebP 块')
    else:
        raise ValueError(f'不支持的图片格式: {extension}')
    if width <= 0 or height <= 0:
        raise ValueError('图片尺寸无效')
    if width * height > _context.MAX_IMAGE_PIXELS:
        raise ValueError(f'图片像素数超过上限 {_context.MAX_IMAGE_PIXELS}')
    return width, height
def _validate_image_file(path):
    try:
        file_stat = os.stat(path)
    except OSError as exc:
        raise ValueError('图片文件不存在或不可访问') from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError('图片路径必须指向普通文件')
    if file_stat.st_size <= 0 or file_stat.st_size > _context.MAX_IMAGE_FILE_SIZE:
        raise ValueError(f'图片文件大小必须在 1 到 {_context.MAX_IMAGE_FILE_SIZE} 字节之间')
    extension = os.path.splitext(path)[1].lower()
    if extension not in _context.SUPPORTED_IMAGE_FORMATS:
        raise ValueError('不支持的图片格式')
    if extension in ('.tif', '.tiff'):
        _tiff_dimensions(path)
        return path
    with open(path, 'rb') as handle:
        header = handle.read(_context.MAX_IMAGE_HEADER_BYTES)
    _image_dimensions_from_header(header, extension)
    return path
def _safe_image_path(path, validate_image=False):
    resolved = _resolve_inside_images_dir(path, must_exist=True)
    if validate_image:
        _validate_image_file(resolved)
    return resolved
def _validate_source_image(path):
    if not isinstance(path, str) or not path:
        raise ValueError('图片路径不能为空')
    if os.path.islink(path):
        raise ValueError('图片源文件不得是符号链接')
    candidate = path
    if not os.path.exists(candidate) and not os.path.isabs(candidate) and not ntpath.isabs(candidate):
        candidate = os.path.join(_resolve_images_root(), path)
    resolved = os.path.realpath(os.path.abspath(candidate))
    if not os.path.exists(resolved):
        raise ValueError('图片文件不存在或不可访问')
    return _validate_image_file(resolved)
def _normalize_stored_image_path(path):
    must_exist = os.path.exists(path)
    resolved = _resolve_inside_images_dir(path, must_exist=must_exist)
    return os.path.relpath(resolved, _resolve_images_root())
def _normalize_image_reference(value):
    if isinstance(value, str):
        path = value
        caption = ''
    elif isinstance(value, dict):
        path = value.get('path')
        caption = value.get('caption', '')
        if not isinstance(path, str) or not isinstance(caption, str):
            raise ValueError('图片引用必须包含字符串 path 和 caption')
    else:
        raise ValueError('图片引用必须是字符串或对象')
    if not path:
        raise ValueError('图片路径不能为空')
    return {'path': _normalize_stored_image_path(path), 'caption': caption}
