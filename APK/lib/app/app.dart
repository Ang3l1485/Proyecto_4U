import 'package:flutter/material.dart';

import '../features/captures/presentation/capture/capture_controller.dart';
import '../features/captures/presentation/capture/capture_page.dart';
import '../features/captures/presentation/dataset/dataset_controller.dart';
import '../features/captures/presentation/dataset/dataset_page.dart';

class DatasetApp extends StatelessWidget {
  const DatasetApp({
    super.key,
    required this.captureController,
    required this.datasetController,
  });

  final CaptureController captureController;
  final DatasetController datasetController;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Dataset georreferenciado',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal),
        useMaterial3: true,
      ),
      home: _HomePage(
        captureController: captureController,
        datasetController: datasetController,
      ),
    );
  }
}

class _HomePage extends StatefulWidget {
  const _HomePage({
    required this.captureController,
    required this.datasetController,
  });

  final CaptureController captureController;
  final DatasetController datasetController;

  @override
  State<_HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<_HomePage> {
  int _selectedIndex = 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Dataset georreferenciado')),
      body: IndexedStack(
        index: _selectedIndex,
        children: <Widget>[
          CapturePage(controller: widget.captureController),
          DatasetPage(controller: widget.datasetController),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (int index) {
          setState(() => _selectedIndex = index);
          if (index == 1) {
            widget.datasetController.loadCaptures();
          }
        },
        destinations: const <NavigationDestination>[
          NavigationDestination(
            icon: Icon(Icons.add_a_photo_outlined),
            selectedIcon: Icon(Icons.add_a_photo),
            label: 'Capturar',
          ),
          NavigationDestination(
            icon: Icon(Icons.grid_view_outlined),
            selectedIcon: Icon(Icons.grid_view),
            label: 'Dataset',
          ),
        ],
      ),
    );
  }
}
