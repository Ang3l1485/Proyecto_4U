import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

class AtomicFileWriter {
  const AtomicFileWriter();

  Future<void> writeBytes(File target, Uint8List bytes) async {
    await target.parent.create(recursive: true);
    final File nextFile = File('${target.path}.next');
    await _deleteIfPresent(nextFile);
    await nextFile.writeAsBytes(bytes, flush: true);
    await _replace(target, nextFile);
  }

  Future<void> writeJson(File target, Object value) {
    final String text = const JsonEncoder.withIndent('  ').convert(value);
    return writeBytes(target, Uint8List.fromList(utf8.encode(text)));
  }

  Future<void> _replace(File target, File nextFile) async {
    final File backupFile = File('${target.path}.backup');
    await _deleteIfPresent(backupFile);
    final bool hadTarget = await target.exists();

    try {
      if (hadTarget) {
        await target.rename(backupFile.path);
      }
      await nextFile.rename(target.path);
      await _deleteIfPresent(backupFile);
    } catch (_) {
      await _deleteIfPresent(nextFile);
      if (hadTarget && await backupFile.exists() && !await target.exists()) {
        await backupFile.rename(target.path);
      }
      rethrow;
    }
  }

  Future<void> _deleteIfPresent(File file) async {
    if (await file.exists()) {
      await file.delete();
    }
  }
}
