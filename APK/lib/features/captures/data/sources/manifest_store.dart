import 'dart:convert';
import 'dart:io';

import '../../../../core/errors/capture_storage_exception.dart';
import '../../domain/entities/capture.dart';
import 'atomic_file_writer.dart';

class ManifestStore {
  ManifestStore({
    required Directory datasetDirectory,
    AtomicFileWriter atomicFileWriter = const AtomicFileWriter(),
  }) : _manifestFile = File(
         '${datasetDirectory.path}${Platform.pathSeparator}manifest.json',
       ),
       _atomicFileWriter = atomicFileWriter;

  final File _manifestFile;
  final AtomicFileWriter _atomicFileWriter;

  Future<List<Capture>> readCaptures() async {
    if (!await _manifestFile.exists()) {
      return <Capture>[];
    }

    try {
      final Object? decoded = jsonDecode(await _manifestFile.readAsString());
      if (decoded is! List<Object?>) {
        throw const FormatException('La raíz no es una lista.');
      }
      return decoded
          .map((Object? entry) {
            if (entry is! Map<Object?, Object?>) {
              throw const FormatException('Una entrada no es un objeto.');
            }
            return Capture.fromJson(entry.cast<String, Object?>());
          })
          .toList(growable: false);
    } on CaptureStorageException {
      rethrow;
    } catch (error) {
      throw CaptureStorageException(
        'El manifest local está corrupto. No se sobrescribió para evitar pérdida de datos.',
        error,
      );
    }
  }

  Future<void> writeCaptures(List<Capture> captures) {
    return _atomicFileWriter.writeJson(
      _manifestFile,
      captures.map((Capture capture) => capture.toJson()).toList(),
    );
  }
}
