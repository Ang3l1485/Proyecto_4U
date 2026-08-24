import 'package:flutter/material.dart';

import 'app/composition_root.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final Widget application = await const CompositionRoot().buildApplication();
  runApp(application);
}
