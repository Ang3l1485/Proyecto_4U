import 'dart:typed_data';

import 'package:image/image.dart' as image;
// The image package's public EXIF API requires this type but does not export it.
// ignore: implementation_imports
import 'package:image/src/util/rational.dart';

import '../../domain/entities/capture_metadata.dart';

class ExifMetadataWriter {
  const ExifMetadataWriter({this.jpegQuality = 90});

  final int jpegQuality;

  Uint8List writeMetadata(Uint8List sourceBytes, CaptureMetadata metadata) {
    final image.Image? decodedImage = image.decodeImage(sourceBytes);
    if (decodedImage == null) {
      throw const FormatException('La imagen no se pudo convertir a JPEG.');
    }

    final bool isAlreadyJpeg =
        sourceBytes.length >= 2 &&
        sourceBytes[0] == 0xff &&
        sourceBytes[1] == 0xd8;
    final Uint8List jpegBytes = isAlreadyJpeg
        ? sourceBytes
        : Uint8List.fromList(
            image.encodeJpg(decodedImage, quality: jpegQuality),
          );
    final image.ExifData exif = image.ExifData();
    exif.imageIfd['ImageDescription'] = metadata.imageLabel;
    exif.imageIfd['Software'] = 'dataset_app';
    exif.imageIfd['Make'] = 'dataset_app';
    exif.imageIfd['Model'] = 'dataset_app';
    exif.imageIfd['Artist'] = metadata.author;
    exif.imageIfd['DateTime'] = _exifDateTime(metadata.timestamp);
    exif.exifIfd['DateTimeOriginal'] = _exifDateTime(metadata.timestamp);
    exif.exifIfd['UserComment'] = _userComment(metadata);
    exif.gpsIfd['GPSLatitudeRef'] = metadata.latitude >= 0 ? 'N' : 'S';
    exif.gpsIfd['GPSLongitudeRef'] = metadata.longitude >= 0 ? 'E' : 'W';
    exif.gpsIfd['GPSLatitude'] = _toDegreesMinutesSeconds(metadata.latitude);
    exif.gpsIfd['GPSLongitude'] = _toDegreesMinutesSeconds(metadata.longitude);

    final double? heading = metadata.compassHeadingDegrees;
    if (heading != null) {
      exif.gpsIfd['GPSImgDirectionRef'] = 'T';
      exif.gpsIfd['GPSImgDirection'] = <Rational>[
        Rational((heading * 10).round(), 10),
      ];
    }

    final Uint8List? result = image.injectJpgExif(jpegBytes, exif);
    if (result == null) {
      throw const FormatException('No fue posible insertar metadatos EXIF.');
    }
    return result;
  }

  String _userComment(CaptureMetadata metadata) {
    final String heading =
        metadata.compassHeadingDegrees?.toStringAsFixed(1) ?? 'unavailable';
    return 'block=${metadata.block};lat=${metadata.latitude.toStringAsFixed(6)};'
        'lon=${metadata.longitude.toStringAsFixed(6)};'
        'direction=${metadata.compassDirection ?? 'unavailable'};'
        'heading=$heading;author=${metadata.author};'
        'sessionId=${metadata.sessionId}';
  }

  String _exifDateTime(DateTime timestamp) {
    final DateTime local = timestamp.toLocal();
    String twoDigits(int value) => value.toString().padLeft(2, '0');
    return '${local.year.toString().padLeft(4, '0')}:'
        '${twoDigits(local.month)}:${twoDigits(local.day)} '
        '${twoDigits(local.hour)}:${twoDigits(local.minute)}:'
        '${twoDigits(local.second)}';
  }

  List<Rational> _toDegreesMinutesSeconds(double value) {
    final double absoluteValue = value.abs();
    final int degrees = absoluteValue.floor();
    final double minutesWithFraction = (absoluteValue - degrees) * 60;
    final int minutes = minutesWithFraction.floor();
    final double seconds = (minutesWithFraction - minutes) * 60;
    return <Rational>[
      Rational(degrees, 1),
      Rational(minutes, 1),
      Rational((seconds * 1000000).round(), 1000000),
    ];
  }
}
